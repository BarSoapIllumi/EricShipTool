#!/usr/bin/env python3
import re
import argparse

def remove_ansi_escape_codes(text):
    ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)

def main(file_name: str):
    with open('temp_output.txt', 'r') as infile, open(file_name, 'w') as outfile:
        for line in infile:
            clean_line = remove_ansi_escape_codes(line)
            outfile.write(clean_line)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean output log.")
    parser.add_argument("file_name", help="Final output file name.")

    args = parser.parse_args()

    main(args.file_name)
