"""
Utilities to parse the output from hubtraf
"""
import json
from dateutil import parser
import argparse

def extract_event(line):
    r"""
    Extract a line of JSON data from a line of fluentd output / raw output
    
    fluentd has strange outputs. It's double JSON encoded, and has a timestamp in it.
    
    >>> line = r'tail.0: [1520570980.336377, {"log":"{\"username\": \"user1\", \"timestamp\": \"2018-03-09T04:49:40.336049Z\"}"}]'
    >>> data = extract_event(line)
    >>> data['username']
    'user1'

    >>> line = r'{"username": "user1"}'
    >>> data = extract_event(line)
    >>> data['username']
    'user1'
    """
    if line.startswith('{'):
        return json.loads(line)
    processed_line = line.split(',', 1)[1].strip()[:-1]

    processed_data = json.loads(json.loads(processed_line)['log'])        
    return processed_data

def prepare_data(inputpath, outputpath):
    """
    Process raw logs from fluentd into a form that can be used for processing.

    1. Parses the JSON output from fluent-bit logs
    2. Sorts them by time so we can do easier stream analyzis on it.

    The sorting loads the whole dataset into memory, so do not pass it too big files!
    """
    events = []
    with open(inputpath) as inputfile:
        for l in inputfile:
            try:
                events.append(extract_event(l))
            except Exception as e:
                print(l)
                continue
    
    events.sort(key=lambda e: parser.parse(e['timestamp']))

    with open(outputpath, 'w') as outputfile:
        for e in events:
            outputfile.write(json.dumps(e) + '\n')


def main():
    """
    Command line utility to process fluent-bit logs into useable hubtraf logs
    """
    argparser = argparse.ArgumentParser()
    argparser.add_argument('inputpath')
    argparser.add_argument('outputpath')

    args = argparser.parse_args()

    prepare_data(args.inputpath, args.outputpath)


if __name__ == '__main__':
    main()