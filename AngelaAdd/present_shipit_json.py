#!/usr/bin/env python3
import json
import argparse
from typing import Any, Dict, List, Union
import re
import subprocess
from datetime import datetime, time

# ANSI color codes
COLORS = {
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "BLACK": '\033[30m',
    "RED": '\033[31m',
    "GREEN": '\033[32m',
    "YELLOW": '\033[93m',
    "BLUE": '\033[34m',
    "MAGENTA": '\033[35m',
    "CYAN": '\033[36m',
    "LIGHT_GRAY": '\033[37m',
    "DARK_GRAY": '\033[90m',
    "BRIGHT_RED": '\033[91m',
    "BRIGHT_GREEN": '\033[92m',
    "BRIGHT_YELLOW": '\033[33m',
    "BRIGHT_BLUE": '\033[94m',
    "BRIGHT_MAGENTA": '\033[95m',
    "BRIGHT_CYAN": '\033[96m',
    "WHITE": '\033[97m'
}

PARTICIPANT_COLORS = [
    COLORS["DARK_GRAY"], COLORS["BLUE"], COLORS["MAGENTA"], COLORS["CYAN"],
    COLORS["RED"], COLORS["GREEN"], COLORS["YELLOW"], COLORS["BRIGHT_BLUE"], COLORS["BRIGHT_MAGENTA"]
]

def load_json(file_name: str) -> Dict[str, Any]:
    """Load JSON data from a file."""
    try:
        with open(file_name) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: The file '{file_name}' was not found.")
        exit(1)
    except json.JSONDecodeError:
        print(f"Error: The file '{file_name}' is not valid JSON.")
        exit(1)

def colorize_event_name(event_name: str) -> str:
    """Colorize event names based on their type and abbreviate names ending with _Pb."""
    event_name_lower = event_name.lower()
    color_map = {
        r'req\d*$': COLORS["BRIGHT_BLUE"],
        r'cfm\d*$': COLORS["BRIGHT_GREEN"],
        r'rej\d*$': COLORS["BRIGHT_RED"],
        r'ind\d*$': COLORS["BRIGHT_YELLOW"],
        r'fwd\d*$': COLORS["BRIGHT_BLUE"],
        r'rsp\d*$': COLORS["BRIGHT_GREEN"]
    }
    
    # Check if the event name contains _Pb and abbreviate the preceding text
    if '_Pb' in event_name:
        parts = event_name.split('_Pb')
        abbreviation = ''.join([char for char in parts[0] if char.isupper()])
        event_name = f"{abbreviation}_Pb{parts[1]}"
    
    for pattern, color in color_map.items():
        if re.search(pattern, event_name_lower):
            return f"{color}{event_name}{COLORS['RESET']}"
    return f"{COLORS['LIGHT_GRAY']}{event_name}{COLORS['RESET']}"

def assign_colors_to_participants(events: List[Dict[str, Any]]) -> Dict[str, str]:
    """Assign colors to participants."""
    participants = {event.get('sender', {}).get('name', '') for event in events}
    participants.update(event.get('receiver', {}).get('name', '') for event in events)
    return {participant: PARTICIPANT_COLORS[i % len(PARTICIPANT_COLORS)] for i, participant in enumerate(participants) if participant}

def truncate_string(s: str, max_length: int) -> str:
    """Truncate a string to a maximum length."""
    return s if len(s) <= max_length else s[:max_length - 3] + "..."

def colorize_element(element: Any) -> str:
    """Colorize JSON elements."""
    if isinstance(element, dict):
        items = [f'{COLORS["BRIGHT_YELLOW"]}"{k}"{COLORS["RESET"]}: {colorize_element(v)}' for k, v in element.items()]
        return '{' + ', '.join(items) + '}'
    elif isinstance(element, list):
        items = [colorize_element(i) for i in element]
        return '[' + ', '.join(items) + ']'
    elif isinstance(element, str):
        return f'{COLORS["BRIGHT_GREEN"]}"{element}"{COLORS["RESET"]}'
    elif isinstance(element, (int, float)):
        return f'{COLORS["BRIGHT_CYAN"]}{element}{COLORS["RESET"]}'
    elif isinstance(element, bool):
        return f'{COLORS["BRIGHT_BLUE"]}{element}{COLORS["RESET"]}'
    elif element is None:
        return f'{COLORS["BRIGHT_RED"]}null{COLORS["RESET"]}'
    else:
        return str(element)

def colorize_json(json_str: str) -> str:
    """Colorize a JSON string."""
    try:
        parsed_json = json.loads(json_str)
        return colorize_element(parsed_json)
    except json.JSONDecodeError:
        return "Invalid JSON"

def convert_list_to_hex_and_ascii(int_list: List[int]) -> str:
    """Convert a list of integers to a hex and ASCII string."""
    ascii_values = ''.join(f'{COLORS["BRIGHT_GREEN"]}{chr(i) if 32 <= i <= 126 else "."}{COLORS["RESET"]}' for i in int_list)
    hex_values = ' '.join(f'{COLORS["BRIGHT_CYAN"]}{i:02x}{COLORS["RESET"]}' for i in int_list)
    return f"{ascii_values} {hex_values}"

def calculate_event_name_width(events: List[Dict[str, Any]]) -> int:
    """Calculate the maximum width of the event names."""
    return max(len(event.get('name', '')) for event in events) + 2

def filter_event_times(events: List[Dict[str, Any]], filter_time: time) -> List[Dict[str, Any]]:
    filtered_events = []

    for event in events:
        timestamp = event.get('sent', event.get('received', ''))
        timestamp = timestamp.replace('Z', '+00:00')[:26]
        try:
            tstamp = datetime.fromisoformat(timestamp).time()

            if tstamp >= filter_time:
                filtered_events.append(event)
        except ValueError:
            continue
    return filtered_events


def print_event(event: Dict[str, Any], show_payload: bool, participant_colors: Dict[str, str], show_queue: bool, event_name_width: int) -> str:
    """Print a single event."""
    timestamp = event.get('sent', event.get('received', 'N/A'))
    sender = truncate_string(event.get('sender', {}).get('name', 'N/A'), 35)
    receiver = truncate_string(event.get('receiver', {}).get('name', 'N/A'), 35)
    
    receive_queue_len = event.get('receive_queue_len', 0)
    event_name = event.get('name', 'N/A')
    msg_payload = event.get('payload', '')
    sender_color = participant_colors.get(sender, COLORS["RESET"])
    receiver_color = participant_colors.get(receiver, COLORS["RESET"])

    output = f"{COLORS['BOLD']}{timestamp:<30}  {COLORS['RESET']}"
    output += f"{sender_color}{sender:<35}  {COLORS['RESET']}"
    output += f"{receiver_color}{receiver:<35}  {COLORS['RESET']}"
    if show_queue:
        output += f"{receive_queue_len:<7}  "
    output += f"{colorize_event_name(truncate_string(event_name, event_name_width)):<{event_name_width + 15}}  "

    if show_payload:
        payload_output = ""
        if isinstance(msg_payload, list) and all(isinstance(i, int) for i in msg_payload):
            payload_output = convert_list_to_hex_and_ascii(msg_payload)
        else:
            msg_payload_str = json.dumps(msg_payload)
            payload_output = colorize_json(msg_payload_str)
        output += f"{payload_output:<50}"
    
    return output

def print_header(show_queue: bool, show_payload: bool, event_name_width: int) -> str:
    """Print the header for the output."""
    header = f"{COLORS['BOLD']}{'Timestamp':<30}  "
    header += f"{'Sender':<35}  "
    header += f"{'Receiver':<35}  "

    if show_queue:
        header += f"{'Queue':<7}  "

    header += f"{'Event Name':<{event_name_width + 6}}  "

    if show_payload:
        header += f"{'Payload':<60}"
    header += f"{COLORS['RESET']}"
    return header

def main(file_name: str, show_payload: bool, show_participants: List[str], exclude_participants: List[str], show_queue: bool, truncate_names: bool, filter_time: str) -> None:
    """Main function to process and pretty-print JSON events."""
    data = load_json(file_name)
    events = data.get('events', [])
    
    if not isinstance(events, list):
        print("Error: The 'events' key is missing or is not a list.")
        exit(1)

    participant_colors = assign_colors_to_participants(events)
    event_name_width = calculate_event_name_width(events)
    if event_name_width > 35 and truncate_names:
        event_name_width = 35

    if filter_time:
        timestamp = datetime.strptime(filter_time, "%H:%M:%S").time()
        events = filter_event_times(events, timestamp)

    filtered_events = [
        event for event in events
            if (not show_participants or any(participant in [event.get('sender', {}).get('name', ''), event.get('receiver', {}).get('name', '')] for participant in show_participants))
            and (not exclude_participants or not any(exclude_str in event.get('sender', {}).get('name', '') or exclude_str in event.get('receiver', {}).get('name', '') for exclude_str in exclude_participants))
    ]

    # Collect the output lines
    output_lines = [print_header(show_queue, show_payload, event_name_width)]
    output_lines.extend(print_event(event, show_payload, participant_colors, show_queue, event_name_width) for event in filtered_events)

    # Join the output lines into a single string
    output = "\n".join(output_lines)

    # Use less -SRXNgi to display the output
    subprocess.run(['less', '-SRXNi'], input=output, universal_newlines=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process and pretty-print JSON events.")
    parser.add_argument("file_name", help="The path to the JSON file to process.")
    parser.add_argument("-p", "--payload", action="store_true", help="Show the payload in the output.")
    parser.add_argument("-s", "--show-participants", type=str, nargs='*', default=[], help="Show events by participants (sender or receiver).")
    parser.add_argument("-e", "--exclude-participants", type=str, nargs='*', default=[], help="Exclude events by participants.")
    parser.add_argument("-q", "--queue", action="store_true", help="Show the receive queue length in the output.")
    parser.add_argument("-n", "--truncate-names", action="store_true", help="Truncate sender and receiver names to match column width.")
    parser.add_argument("-t", "--timestamp", type=str, help="Filter events at/after specified timestamp in format (HH:MM:SS).")

    args = parser.parse_args()

    main(args.file_name, args.payload, args.show_participants, args.exclude_participants, args.queue, args.truncate_names, args.timestamp)
