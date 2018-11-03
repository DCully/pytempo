# PyTempo
Detect BPM from audio data streams.

## What?
PyTempo is pure Python implementation of causal tempo detection for data streams from 16-bit, 44100Hz PCM audio data.
If you open up a 16-bit, 44100Hz audio file and feed its data into an instance of a `TempoDetector`, the detector
will (from a separate thread) publish BPM data into the publisher you injected at runtime.

The `scripts/detect_tempo.py` example script demonstrates how to use the module in code.

The test cases in `test/pytempo_test.py` demonstrate that this algorithm correctly detects the BPM of several
pop song samples to within 3 BPM.

## How?
The TempoDetector class aggregates and processes samples in batches of1024 samples at a time. It computes the
energy per frequency band per 1024 samples, and stores trailing histories of these energy values. When it processes
a batch whose energy in a given frequency band is significantly different than the trailing average, it records a
'beat' event at that moment in its time line.

Using the trailing beat event records, the TempoDetector tests all 'danceable' BPM value intervals (~73-136 BPM),
and for each frequency band, selects the BPM value for which the most intervals align as a 'vote' for that BPM.
Then it publishes the BPM value for which the most frequency bands have currently 'voted' into the publisher
you injected when you initialized the TempoDetector.

# Why?
To help teach robots to dance, of course! :-D

This BPM detection implementation is written in pure Python for ease of installation and deployment.
