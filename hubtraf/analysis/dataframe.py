"""
Dataframe related analysis helpers
"""

import io
import json

import pandas as pd
import streamz


def accumulate_to_df(logfile, accumulate_func):
    """
    Run an accumulator against a logfile, and return output in a dataframe
    """
    stream = streamz.Stream()

    with open(logfile) as infile, io.StringIO() as outfile:
        stream.map(json.loads).accumulate(
            accumulate_func, returns_state=True, start={}
        ).sink(lambda e: outfile.write(json.dumps(e) + '\n'))
        for l in infile:
            stream.emit(l)
        outfile.seek(0)
        dataframe = pd.read_json(outfile, lines=True)
    dataframe.set_index('timestamp', inplace=True)
    return dataframe


def logfile_to_df(logfile):
    """
    Load a logfile into a dataframe

    Will set timestamp as index
    """
    df = pd.read_json(logfile, lines=True)
    df.set_index('timestamp', inplace=True)
    return df
