#!/usr/bin/env python3

import struct
import sys
import argparse
import subprocess
from datetime import datetime
import os
import re
import glob
import json

ITC_SEND = 0
ITC_RECV = 1

def convert_hex_data(data):
  if type(data) == int: # don't need conversion if it is already converted
    return data

  try:
    if args.little_endian:
      return struct.unpack('<I', data)[0]
    else:
      return struct.unpack('>I', data)[0]
  except Exception as e:
    # instead of crashing, just mark converted data as -1, i.e. failed
    return -1

def print_stderr(text):
  print(text, file=sys.stderr, flush=True)

def is_text(fn):
    msg = subprocess.Popen(["file", "--mime", fn], stdout=subprocess.PIPE, universal_newlines=True).communicate()[0]
    return "text" in msg or "empty" in msg

# Locates the ship header in the file
def find_ship_header(f):
  data = f.read(4)
  while data != b'SHIP':
    data = f.read(4)

  endian = ''
  bom = struct.unpack('<H', f.read(2))[0]

  # legacy LE version 1 occupied these bytes
  if bom == 0xFEFF or bom == 1:
    endian = '<'
  else:
    endian = '>'

  version = struct.unpack(endian + 'H', f.read(2))[0]
  # legacy version 1 appears as 0 here
  if version == 1 or version == 0:
    return (True, endian, 1)
  elif version == 2:
    return (True, endian, 2)
  else:
    return (False, endian, 0)

## Reads struct SignalInfo from file
def read_binary(path, keep_zeros):
  with open(path, 'rb') as f:
    header = find_ship_header(f)
    if not header[0]:
      print_stderr("%s is not a valid ship file" % path)
      return []

    entries = []

    if header[2] == 1:
      struct_format = header[1] + 'HxxIIIiiII'
      for data in struct.iter_unpack(struct_format, f.read()):
        if data[4] != 0 or keep_zeros: # If timestamp is null, list is not full. Haha, that rhymes.
          entries.append({'type': data[0], 'source': data[1], 'sender':data[2], \
                          'receiver':data[3], 'seconds':data[4], \
                           'microseconds':data[5], 'signo':data[6], 'procId':b'', 'connId':b''})

    elif header[2] == 2:
      struct_format = header[1] + 'iiIIIII4s4s'
      for data in struct.iter_unpack(struct_format, f.read()):
        if data[0] != 0 or keep_zeros: # If timestamp is null, list is not full. Haha, that rhymes.
          entries.append({'type': data[3], 'source': data[2], 'sender':data[4], \
                          'receiver':data[5], 'seconds':data[0], \
                          'microseconds':data[1], 'signo':data[6], \
                          'procId':data[7], 'connId':data[8]})

    return entries

def clear_file(path):
  with open(path, 'r+b') as f:
    header = find_ship_header(f)
    if not header[0]:
      print_stderr("%s is not a valid ship file" % path)
      return

    size = os.stat(path).st_size
    size = size - f.tell()
    f.write(b'\x00' * size)

def read_text(path):
  entries = []
  with open(path) as fp:
    while True:
      line = fp.readline()
      if not line:
        break
      line = line.split('#')[0]
      if not line:
          continue
      fields = line.split()
      timestamp = fields[0].split(".")
      entry = {'seconds': int(timestamp[0]), 'microseconds': int(timestamp[1]), \
                      'type': int(fields[1]), 'source': int(fields[2]), 'sender': int(fields[3]), \
                      'receiver': int(fields[4]), 'signo': int(fields[5], 16)}
      if len(fields) == 7: # hexdata is present
        if len(fields[6]) == 32:
          # They don't make it easy to convert a literal escaped string to the actual bytes..
          entry['procId'] = ((fields[6])[:int(len(fields[6])/2)]).encode().decode('unicode-escape').encode('latin1')
          entry['connId'] = ((fields[6])[int(len(fields[6])/2):]).encode().decode('unicode-escape').encode('latin1')
        else: # handling of bug, reformat from \xffffffhh to \xhh
          split = fields[6].split("\\x")
          fixed = [int(f, 16) & int("0xFF", 16) for f in split[1:]]
          fixed_proc_string = ''.join("\\x%02x" % f for f in fixed[:4])
          fixed_conn_string = ''.join("\\x%02x" % f for f in fixed[4:])
          entry['procId'] = fixed_proc_string.encode().decode('unicode-escape').encode('latin1')
          entry['connId'] = fixed_conn_string.encode().decode('unicode-escape').encode('latin1')
      elif len(fields) == 8: # two integer is present
          entry['procId'] = int(fields[6])
          entry['connId'] = int(fields[7])
      else: # proc id and conn id is not present
        entry['procId'] = b''
        entry['connId'] = b''

      entries.append(entry)
  return entries

# parse output from um list or um trace
def parse_um(output):
  mailboxes = {}
  # split on two or more spaces
  header = re.split(r'\s{2,}', output.readline().lstrip())
  i = 0
  id_index = 0
  name_index = 0

  for col in header:
    if "Id" in col:
      id_index = i
    if "Name" in col:
      name_index = i
    i += 1

  for line in output:
    columns = line.lstrip().split()
    try:
      mailboxes[int(columns[id_index])] = columns[name_index]
    except IndexError:
      continue
  return mailboxes

def parse_signals(path):
  signals = {}
  with open(path) as fp:
    while True:
      line = fp.readline()
      if not line:
        break
      fields = line.split()
      signo = int(fields[2])
      if not signo in signals:
        signals[signo] = fields[0]
  return signals

# Get mailbox list by executing um list
def get_mailboxes():
  try:
    proc = subprocess.Popen(['um','list'], stdout=subprocess.PIPE, universal_newlines=True)
  except OSError:
    return {}
  else:
    mailboxes = parse_um(proc.stdout)
    proc.wait()
  return mailboxes

# Reads mailbox list from specified file
def read_mailboxes(path):
  mailboxes = {}
  with open(path) as fp:
    mailboxes = parse_um(fp)
  return mailboxes

# Print output in the raw format provided by GDB in earlier script
def print_ship_entries_text(entries):
  for data in entries:
    if args.dont_convert_hex_data:
      print("%u.%06u %u %u %u %u 0x%x %s%s" % (data['seconds'], data['microseconds'], data['type'], \
                                               data['source'], data['sender'], data['receiver'], \
                                               data['signo'], "".join("\\x%02x" % i for i in data['procId']), \
                                               "".join("\\x%02x" % i for i in data['connId'])))
    else:
      print("%u.%06u %u %u %u %u 0x%x %u %u" % (data['seconds'], data['microseconds'], data['type'], \
                                                data['source'], data['sender'], data['receiver'], \
                                                data['signo'], convert_hex_data(data['procId']), convert_hex_data(data['connId'])))

# Get all mailboxes beloning to this lm
def get_local_boxes(entries):
  boxes = set()
  for i in entries:
      if i['type'] == ITC_SEND:
        boxes.add(i['sender'])
      elif i['type'] == ITC_RECV:
        boxes.add(i['receiver'])
  return boxes

def get_all_boxes(entries):
  boxes = set()
  for entry in entries:
    boxes.add(entry['sender'])
    boxes.add(entry['receiver'])
  return boxes

def get_all_signals(entries):
  return set( d['signo'] for d in entries )

def pair_key(entry):
  return (entry['signo'], entry['sender'], entry['receiver'], entry['procId'], entry['connId'])

def is_pair(rx, tx):
  if not 'pair' in rx.keys():
    sent = tx['seconds'] + tx['microseconds']/1e6
    received = rx['seconds'] + rx['microseconds']/1e6
    return sent < received
  else:
      return False

def find_pairs(entries):
  tx = [i for i in entries if i['type'] == ITC_SEND]
  rx = [i for i in entries if i['type'] == ITC_RECV]

  # Setup a look-up table of all RX signals,
  # indexed on (signo, receiver, sender, data)
  rx_keys = set([pair_key(i) for i in entries])
  rx_map = {i:[] for i in rx_keys}
  for entry in rx:
    rx_map[pair_key(entry)].append(entry)

  # For each TX signal, check all matching RX, and also check
  # if already claimed by another TX, and that TX timestamp < RX timestamp.
  # Select first match
  for entry in tx:
    possible_pairs = [i for i in rx_map[pair_key(entry)] if is_pair(i, entry)]
    if possible_pairs:
      entry['pair'] = possible_pairs[0]
      possible_pairs[0]['pair'] = entry


# Removes internal send events to prevent duplicates
def filter_duplicates(entries):
  return [i for i in entries if i['type'] == ITC_SEND or 'pair' not in i.keys()]


# Prints CSV format of ship data
def print_ship_entries(entries, mailboxes, signals):
  print("time, direction, queue_time, from_msgboxId, from_name, to_msgboxId, to_name, signalNumber, signalName, procId, connId")
  entries = filter_duplicates(entries)
  for data in entries:

    try:
      sender = mailboxes[data['sender']]
    except KeyError:
      sender = '<unknown>'

    try:
      receiver = mailboxes[data['receiver']]
    except KeyError:
      receiver = '<unknown>'

    try:
      signal = signals[data['signo']]
    except KeyError:
      signal = '<unknown>'

    timestamp = datetime.strftime(datetime.utcfromtimestamp(data['seconds']+data['microseconds']/1e6), '%Y-%m-%d %H:%M:%S.%f')

    if data['type'] == ITC_SEND:
      direction = "S"
    else:
      direction = "R"

    try:
      pair = data['pair']
      diff = pair['seconds'] + pair['microseconds']/1e6 - (data['seconds'] + data['microseconds']/1e6)
      queue_time = "%+.6f" % diff
    except KeyError:
      queue_time = "<unknown>"

    if args.dont_convert_hex_data:
      print("%s, %s, %s, %u, %s, %u, %s, 0x%x, %s, {%s %s}" % (timestamp,
                                                               direction,
                                                               queue_time,
                                                               data['sender'], sender,
                                                               data['receiver'], receiver,
                                                               data['signo'], signal,
                                                               " ".join("%02x" % i for i in data['procId']),
                                                               " ".join("%02x" % i for i in data['connId'])))
    else:
      print("%s, %s, %s, %u, %s, %u, %s, 0x%x, %s, %u, %u" % (timestamp,
                                                              direction,
                                                              queue_time,
                                                              data['sender'], sender,
                                                              data['receiver'], receiver,
                                                              data['signo'], signal,
                                                              convert_hex_data(data['procId']),
                                                              convert_hex_data(data['connId'])))

def print_json(entries, mailboxes, signals):
  for data in entries:
    # Avoid infinite recursion caused by pairs referencing each other
    data.pop('pair', 0)

    try:
      data['senderName'] = mailboxes[data['sender']]
    except KeyError:
      pass

    try:
      data['receiverName'] = mailboxes[data['receiver']]
    except KeyError:
      pass

    try:
      data['signalName'] = signals[data['signo']]
    except KeyError:
      pass

    data['seconds'] += data['microseconds']/1e6
    data.pop('microseconds')
    data['timestamp'] = datetime.strftime(datetime.utcfromtimestamp(data['seconds']), '%Y-%m-%d %H:%M:%S.%f')

    if args.dont_convert_hex_data:
      data['procId']  = "".join("\\x%02x" % i for i in data['procId'])
      data['connId']  = "".join("\\x%02x" % i for i in data['connId'])
    else:
      data['procId'] = convert_hex_data(data['procId'])
      data['connId'] = convert_hex_data(data['connId'])

  print(json.dumps(entries, indent=2))

def print_uml(entries, mailboxes, signals):
  entries = filter_duplicates(entries)
  local_boxes = get_local_boxes(entries)
  all_boxes = get_all_boxes(entries)

  print("@startuml")
  print("skinparam defaultFontName Consolas")
  print("skinparam defaultFontSize 14")
  print("skinparam backgroundColor white")
  print("skinparam arrowColor darkred")
  print("box \"Application\"")
  for box in local_boxes:
    if box in mailboxes.keys():
      print("participant \"%s\\n%u\" as %u" % (mailboxes[box], box, box))
    else:
      print("participant " + str(box))
  print("end box")

  print("")

  for box in all_boxes:
    if box not in local_boxes:
      if box in mailboxes.keys():
        print("participant \"%s\\n%u\" as %u" % (mailboxes[box], box, box))
      else:
        print("participant " + str(box))

  print("")
  print("")

  last_time = 0
  if len(entries) > 0:
    last_time = entries[0]['seconds']

  for entry in entries:

    diff = entry['seconds'] - last_time
    if diff > 1:
      print("...%u second(s) passed..." % diff)
    last_time = entry['seconds']

    try:
      signal = signals[entry['signo']]
    except KeyError:
      signal = "0x%x" % entry['signo']
    isig=signal.upper()
    print("%u %s%s%s %u :  %s "  % (entry['sender'],
                                    "--" if isig.endswith("CFM") or isig.endswith("REJ") or isig.endswith("_R")
                                            or isig.endswith("ACK") or isig.endswith("REPLY") or isig.endswith("RSP")
                                            else "-",
                                    "[#red]" if isig.endswith("REJ") else "",
                                    ">>" if isig.endswith("IND") or isig.endswith("FWD")
                                            else ">",
                                    entry['receiver'],
                                    signal))


  print("== Memory was dumped! ==")
  print("@enduml")

# Output two tables with all data grouped on signal id and mailbox id, respectively,
# with total counts and time of first/last event.
def print_summary(entries, mailboxes, signals):
  entries = filter_duplicates(entries)

  alls = get_all_signals(entries)
  length=max( (len(signals[s]) if s in signals else 9) for s in alls )+1
  fmt="{0:<10} {1:<{5}} {2:<5} {3:<27} {4}"
  print(fmt.format("# Signal", "Name", "Count", "First", "Last", length))
  for signo in sorted(alls, key=lambda s: (1,signals[s].upper()) if s in signals else (2,s)):
    print(fmt.format("0x{0:07x}".format(signo),
                     signals[signo] if signo in signals else "<unknown>",
                     sum( 1 for e in entries if e['signo'] == signo ),
                     datetime.strftime( datetime.utcfromtimestamp(
                       min( e['seconds']+e['microseconds']/1e6 for e in entries if e['signo'] == signo )),
                       '%Y-%m-%d %H:%M:%S.%f'),
                     datetime.strftime( datetime.utcfromtimestamp(
                       max( e['seconds']+e['microseconds']/1e6 for e in entries if e['signo'] == signo )),
                       '%m-%d %H:%M:%S.%f'),
                     length))

  allm = get_all_boxes(entries)
  length=max( (len(mailboxes[m]) if m in mailboxes else 9) for m in allm )+1
  fmt="{0:<10} {1:<{6}} {2:<5} {3:<9} {4:<27} {5}"
  print()
  print(fmt.format("# Mailbox", "Name", "Sent", "Received", "First", "Last", length))
  for box in sorted(allm, key=lambda b: (1,mailboxes[b].upper()) if b in mailboxes else (2,b)):
    print(fmt.format(box,
                     mailboxes[box] if box in mailboxes else "<unknown>",
                     sum(1 for e in entries if e['sender'] == box),
                     sum(1 for e in entries if e['receiver'] == box),
                     datetime.strftime( datetime.utcfromtimestamp(
                       min( (e['seconds']+e['microseconds']/1e6 for e in entries if e['sender'] == box or e['receiver'] == box), default=0 )),
                       '%Y-%m-%d %H:%M:%S.%f'),
                     datetime.strftime( datetime.utcfromtimestamp(
                       max( (e['seconds']+e['microseconds']/1e6 for e in entries if e['sender'] == box or e['receiver'] == box), default=0 )),
                       '%m-%d %H:%M:%S.%f'),
                     length))

def filter_ids(filter, idset, idmap):
  if not filter: # No filter means all ids go
    return (idset, set())

  # A filter is a comma-delimited string of string patterns ("str"), decimal numbers ("dec"), hexadecimal numbers ("hex"),
  # or a number ranges ("dec"+"dec2" and "hex"+"hex2", respectively). String patterns are case insensitive regular expressions.
  # To match a full string, use ^ and $. Strings can't contain commas.
  # A match item prefixed with '-' negates the match. A '~' prefix creates an intersection, and no prefix a union with previous matches.
  #
  # Examples:
  #   A4CI_, ^NC_, +_REQ$
  #   REJ$, 43, 0x17000
  #   -cfm$, 0x17000-0x17fff, -0x17a34
  regex = r"\s*(?P<ex>[-~])?(?:(?P<dec>\d+)(?:\s*-\s*(?P<dec2>\d+))?|(?P<hex>0x[0-9a-f]+)(?:\s*-\s*(?P<hex2>0x[0-9a-f]+))?|(?P<str>[^, ][^,]*?))\s*(?:,+|$)"
  selected=set(idset)
  unselected=set()
  for matchNum, match in enumerate(re.finditer(regex, filter, re.IGNORECASE), start=1):
    if matchNum==1 and match.group("ex") != "-":
      selected=set()

    if match.group("str"):
      try:
        expr=re.compile(match.group("str"), re.IGNORECASE)
      except Exception as e:
        print("Invalid regular expression '{}': {}".format(match.group("str"), e), file=sys.stderr)
        exit(1)
      matcher = lambda s: expr.search(idmap[s] if s in idmap else "<unknown>")
    elif match.group("dec"):
      lo=int(match.group("dec"))
      hi=int(match.group("dec2")) if match.group("dec2") else lo
      matcher = lambda s: s >= lo and s <= hi
    else: # hex
      lo=int(match.group("hex"), 16)
      hi=int(match.group("hex2"), 16) if match.group("hex2") else lo
      matcher = lambda s: s >= lo and s <= hi

    if match.group("ex")=="-":
      selected = selected.difference( s for s in selected if matcher(s) )
      unselected.update(s for s in idset if matcher(s))
    elif match.group("ex")=="~":
      selected = set( s for s in selected if matcher(s) )
    else:
      selected.update( s for s in idset if matcher(s) )
  return (selected,unselected)

def find_signal_file():
  home_file = os.path.expanduser("~/signal_list")
  if os.path.exists(home_file):
    return home_file

  installed_file = os.path.dirname(os.path.realpath(__file__)) + "/signal_list"
  if os.path.exists(installed_file):
    return installed_file

  return None

def get_input_files(file_args):
  files = []

  oldcwd = os.getcwd()
  if "APP_TMP" in os.environ.keys():
    search_dir = os.environ["APP_TMP"]
  else:
    search_dir = "/tmp"

  if len(file_args) == 0:
    os.chdir(search_dir)
    matches = glob.glob("**/*.ship", recursive=True)
    files.extend([search_dir + "/" + i for i in matches])
    os.chdir(oldcwd)

  else:
    for i in file_args:
      if os.path.exists(i):
        files.append(i)
      else:
        os.chdir(search_dir)
        matches = glob.glob("**/" + i + "*.ship", recursive=True)
        files.extend([search_dir + "/" + i for i in matches])
        os.chdir(oldcwd)

  return files

def stream_files(input_files):
  # lowest prio, will consume one core whhile running
  os.nice(20)

  previous_data = {}
  for f in  get_input_files(input_files):
    try:
      previous_data[f] = read_binary(f, True)
      print_stderr ("Using input %s" % f)

    except FileNotFoundError as e:
      continue

  while True:
    for f in  get_input_files(input_files):
      if f in previous_data.keys():
        previous = previous_data[f]
      else:
        print_stderr ("Detected new input %s" % f)
        previous = []

      try:
        entries = read_binary(f, True)
      except FileNotFoundError as e:
        continue

      i = 0
      truncated = True
      overlaps = False
      while i < len(entries):
        entry = entries[i]
        if entry['seconds'] != 0 and (i >= len(previous) or previous[i] != entry):
          if args.dont_convert_hex_data:
            print("%u.%06u %u %u %u %u 0x%x %s%s" % (entry['seconds'], entry['microseconds'], entry['type'], \
                                                     entry['source'], entry['sender'], entry['receiver'], \
                                                     entry['signo'], "".join("\\x%02x" % i for i in entry['procId']), \
                                                     "".join("\\x%02x" % i for i in entry['connId'])))
          else:
            print("%u.%06u %u %u %u %u 0x%x %u %u" % (entry['seconds'], entry['microseconds'], entry['type'], \
                                                      entry['source'], entry['sender'], entry['receiver'], \
                                                      entry['signo'], convert_hex_data(entry['procId']), convert_hex_data(entry['connId'])))

        elif entry['seconds'] == 0:
          truncated = False
          overlaps = True
        else:
          overlaps = True
        i += 1

      if not overlaps and len(previous) != 0:
        print_stderr("Signals may have been lost from input %s." % (f))
      if len(previous) == 0 and truncated:
        print_stderr("Initial signals may have been lost from input %s" % f)

      previous_data[f] = entries


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description='Interprets and transforms SHIP files to more human readable formats.')
  parser.add_argument('input_file', metavar='FILE', nargs='*', help='the .ship files to interpret. All found in /tmp if not specified')
  parser.add_argument('--mailboxes', help='a file which contains a list of space delimited mailbox- name/number associations. Format: See output from \'um list\' command')
  parser.add_argument('--signals', help='a file which contains a list of signal- name/number associations. Format: \'NAME NUMBER_HEX NUMBER_DEC\'')
  parser.add_argument('--signal-filter', metavar='FILTER', help='comma delimited list of signals to include (or exclude if prepended with -)')
  parser.add_argument('--mailbox-filter', metavar='FILTER', help='comma delimited list of mailboxes to include (or exclude if prepended with -)')
  # used for testing, to compare with outputted file
  parser.add_argument('--dont_convert_hex_data', action='store_true', help='if hex data should not be converted to procId and connId')
  parser.add_argument('--little_endian', action='store_true', help='if little endian is used for hex data, deafult is big endian')
  group = parser.add_mutually_exclusive_group(required=False)
  group.add_argument('--text', action='store_true', help='print raw output. Will not look up any names')
  group.add_argument('--stream', action='store_true', help='Stream ship data as it is written in raw format')
  group.add_argument('--uml', action='store_true', help='print plantuml output')
  group.add_argument('--json', action='store_true', help='print parsed shipdata as JSON')
  group.add_argument('--summary', action='store_true', help='print counts of signals and mailboxes')
  group.add_argument('--clear', action='store_true', help='clears ship logs. Only possible in a production environment')
  args = parser.parse_args()

  # stream detects files as they are created
  if args.stream:
    stream_files(args.input_file)
    exit(0)

  files = get_input_files(args.input_file)
  if len(files) == 0:
    print_stderr("No ship files found!")
    exit(1)

  if args.clear:
    print ("Clearing %u files" % len(files))
    for i in files:
      clear_file(i)
    exit(0)

  data = []
  for f in files:
    if is_text(f):
      data.extend(read_text(f))
    else:
      data.extend(read_binary(f, False))

  data = sorted(data, key = lambda i: (i['seconds'], i['microseconds']))
  find_pairs(data)

  if args.text:
    print_ship_entries_text(data)
    exit(0)

  if args.mailboxes:
    mailboxes = read_mailboxes(args.mailboxes)
  else:
    mailboxes = get_mailboxes()

  if args.signals:
    signals = parse_signals(args.signals)
  else:
    f = find_signal_file()
    if f is not None:
      signals = parse_signals(f)
    else:
      signals = {}

  if args.signal_filter or args.mailbox_filter:
    (alls,_) = filter_ids( args.signal_filter, get_all_signals(data), signals )
    if args.mailbox_filter and args.mailbox_filter.find(":") >= 0:
      (f1,f2) = args.mailbox_filter.split(":")
      (allm1,_) = filter_ids( f1, get_all_boxes(data), mailboxes )
      (allm2,_) = filter_ids( f2, get_all_boxes(data), mailboxes )
      data = [ d for d in data if d['signo'] in alls
               and ( d['sender'] in allm1 and d['receiver'] in allm2
                     or d['sender'] in allm2 and d['receiver'] in allm1)]
    else:
      (allm,exm) = filter_ids( args.mailbox_filter, get_all_boxes(data), mailboxes )
      data = [ d for d in data if d['signo'] in alls
               and ( d['sender'] in allm or d['receiver'] in allm )
               and d['sender'] not in exm and d['receiver'] not in exm]
    if len(data)==0:
      print_stderr("No signals selected! Check your filters or try --summary without filters.", file=sys.stderr)
      exit(1)

  if args.uml:
    print_uml(data, mailboxes, signals)
    exit(0)

  if args.json:
    print_json(data, mailboxes, signals)
    exit(0)

  if args.summary:
    print_summary(data, mailboxes, signals)
    exit(0)

  print_ship_entries(data, mailboxes, signals)

