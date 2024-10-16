from flask import Flask, jsonify, send_file, send_from_directory, request
import os
import markdown
from datetime import datetime, timedelta
import re
import html2text
import json
from calendar_utils import CACHE_FILE, fetch_and_filter_calendar_events
import logging

app = Flask(__name__, static_folder="static")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Update the CACHE_FILE path
CACHE_EXPIRY = timedelta(hours=1)


def load_cache():
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        if datetime.fromisoformat(cache["timestamp"]) + CACHE_EXPIRY > datetime.now():
            return cache["events"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def save_cache(events):
    cache = {"timestamp": datetime.now().isoformat(), "events": events}
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


def generate_unique_filename():
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H%M%S")
    return f"{today}-{timestamp}-entry.md"


@app.route("/api/journal-entries")
def get_journal_entries():
    logging.info("GET /api/journal-entries")
    entries = []
    for filename in os.listdir("data"):
        if filename.endswith(".md"):
            file_path = os.path.join("data", filename)
            with open(file_path, "r") as f:
                content = f.read().split("\n")
                title = content[0].strip("# ")  # Remove Markdown heading syntax
                body = content[1] if len(content) > 1 else ""
                date_str = filename.split("-")[:3]
                date = "-".join(date_str[:3])  # Keep as YYYY-MM-DD
                preview = body[:100] + "..." if len(body) > 100 else body
                entries.append(
                    {
                        "date": date,
                        "title": title,
                        "preview": preview,
                        "filename": filename,
                    }
                )
    # Sort entries by filename in descending order (latest first)
    entries.sort(key=lambda x: x["filename"], reverse=True)
    return jsonify(entries)


@app.route("/api/journal-entry/<filename>")
def get_journal_entry(filename):
    logging.info(f"GET /api/journal-entry/{filename}")
    file_path = os.path.join("data", filename)
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            content = f.read()
            # Convert Markdown to HTML for display in the editor
            html_content = markdown.markdown(content)
            return html_content
    return "Entry not found", 404


@app.route("/")
def serve_journal():
    logging.info("GET /")
    return send_file("journal.html")


@app.route("/static/<path:path>")
def serve_static(path):
    logging.info(f"GET /static/{path}")
    return send_from_directory("static", path)


@app.route("/api/new-entry", methods=["POST"])
def create_new_entry():
    logging.info("POST /api/new-entry")
    filename = generate_unique_filename()
    title = f"Today, ..."
    file_path = os.path.join("data", filename)

    # Create a new entry file with minimal content
    with open(file_path, "w") as f:
        f.write(f"# {title}\n\n")

    return jsonify(
        {
            "filename": filename,
            "title": title,
            "date": filename.split("-")[0],
            "preview": "",
        }
    )


@app.route("/api/update-entry/<filename>", methods=["POST"])
def update_entry(filename):
    logging.info(f"POST /api/update-entry/{filename}")
    file_path = os.path.join("data", filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "Entry not found"}), 404

    content = request.json.get("content")
    if not content:
        return jsonify({"error": "No content provided"}), 400

    # Split the content into lines, preserving empty lines
    lines = content.split("\n")

    # Ensure there's at least one line
    if not lines:
        return jsonify({"error": "Empty content"}), 400

    # The first non-empty line is the title
    title = next((line for line in lines if line.strip()), "Untitled")

    # The rest is the content, preserving all newlines
    body = "\n".join(lines[lines.index(title) + 1 :])

    # Combine title and body, ensuring two newlines after the title
    full_content = f"{title}\n\n{body}"

    # Write the content to the file
    with open(file_path, "w") as f:
        f.write(full_content)

    return jsonify({"message": "Entry updated successfully"})


@app.route("/api/calendar-events")
def get_calendar_events():
    logging.info("GET /api/calendar-events")
    force_refresh = request.args.get("refresh", "").lower() == "true"
    cached_events = None if force_refresh else load_cache()

    if cached_events:
        return jsonify(cached_events)

    try:
        all_events, todays_events = fetch_and_filter_calendar_events()
        events = {"all_events": all_events, "todays_events": todays_events}
        save_cache(events)
        return jsonify(events)
    except Exception as e:
        print(f"Error fetching calendar events: {e}")
        cached_events = load_cache()
        if cached_events:
            return jsonify(cached_events)
        return jsonify({"error": "Unable to fetch events and no cache available"}), 500


@app.route("/api/calendar-events/<date>")
def get_calendar_events_for_date(date):
    logging.info(f"GET /api/calendar-events/{date}")
    force_refresh = request.args.get("force_refresh", "").lower() == "true"
    try:
        all_events, _ = fetch_and_filter_calendar_events(
            target_date=date, force_refresh=force_refresh
        )

        date_events = []
        for event in all_events:
            try:
                event_parts = event.split(", ")
                event_dict = {
                    part.split(": ")[0]: ": ".join(part.split(": ")[1:])
                    for part in event_parts
                }

                event_date = event_dict["Start time"].split("T")[0]
                if event_date == date:
                    date_events.append(
                        {
                            "summary": event_dict["Summary"],
                            "start": {"dateTime": event_dict["Start time"]},
                            "end": {"dateTime": event_dict["End time"]},
                        }
                    )
            except Exception as e:
                logging.error(f"Error processing event: {e}")

        logging.info(f"Found {len(date_events)} events for date {date}")
        return jsonify(date_events)
    except Exception as e:
        logging.error(f"Error fetching events for date {date}: {str(e)}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
