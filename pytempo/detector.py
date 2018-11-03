import time

from threading import Thread
from collections import deque
from queue import Queue

import numpy


def smooth_beats(beat_history):
    """
    apply some very simple clustering to group nearby beats
    TODO - improve this
    """
    history = [False] * len(self._beat_history)
    in_beat = False
    beat_start = -1
    beat_end = -1
    for i in range(len(self._beat_history)):

        # the current value
        now_is_beat = self._beat_history[i]

        # update in_beat value
        if now_is_beat and not in_beat:
            # case - start of a new beat
            beat_start = i
            in_beat = True
        elif now_is_beat and in_beat:
            # case - a straight continuation of a beat
            beat_end = i
            in_beat = True
        elif not now_is_beat and in_beat:
            # case - maybe in a dodgy beat, or maybe the beat is over
            if i + 1 < len(history):
                # if the next one right after this is a beat event
                in_beat = True
            else:
                in_beat = False
                beat_end = i
        else:
            # case - not in a beat, and not seeing a new one starting
            in_beat = False

        # react to in_beat value
        if in_beat:
            # build up more data, waiting for this beat to end
            continue
        else:
            # consolidate the trailing events into a single, centralized beat
            beat_location = int(beat_start + beat_end / 2.0)
            history[beat_location] = True

    return history


def compute_max_gap_from(history):
    max_gap = 0
    last = None
    for idx in range(len(history)):
        was_beat = history[idx]
        if was_beat:
            if last is None:
                last = idx
            else:
                gap = idx - last
                if gap > max_gap:
                    max_gap = gap
    if max_gap > 0:
        return max_gap
    return None


class TempoDetector(object):

    def __init__(self, publisher):
        self._in_queue = Queue(maxsize=1024)
        self._publisher = publisher
        self._energy_hist_per_freq_band = [deque(maxlen=43)] * 32
        self._beat_history = deque(maxlen=43*7)  # ~7 seconds
        self._processing_thread = Thread(
            target= self._run_data_processing,
            daemon=True,
        )
        self._processing_thread.start()

    def _detect_tempo(self):
        """
        Look at the beat history and derive a tempo, publishing
        the tempo (a BPM) as an int if one is found (do not publish
        if you do not find a convincing tempo).
        """

        # wait for a full history before inspecting it
        if not len(self._beat_history) == 43*7:
            return

        # apply some very simple clustering to group nearby beats
        history = smooth_beats(self._beat_history)

        # compute tempo from smoothed beats
        # TODO - this is naive - apply a list of BPM templates
        max_gap = compute_max_gap_from(history)
        if max_gap is None:
            return None

        # each slot is 1/43 of a second
        # so this is effectively how long each beat takes up
        # 60bpm would mean that max_gap_length_seconds == 1
        max_gap_length_seconds = max_gap * (1.0 / 43.0)

        # convert seconds per beat to beats-per-second and then beats-per-minute
        bps = 1.0 / max_gap_length_seconds
        bpm = bps * 60.0

        # only return reasonable BPM values
        if 70 < bpm < 150:
            return bpm
        return None

    def _detect_beat(self, data):
        """
        Process the raw data to detect beats in this instant, and update
        self._beat_history accordingly with a True or False value.
        """
        # collapse data into one channel
        data = [sum(d) / len(d) for d in data]

        # compute fft of samples (giving us 1024 complex numbers)
        data = numpy.fft.fft(data)

        # compute square of modulus of each sample
        # this gives us amplitudes per frequency
        ampls_per_freq = [d.real*d.real + d.imag*d.imag for d in data]

        # compute sub-band energies for this 'instant'
        inst_sub_band_energies = []
        for sub_band in range(32):
            sub_band_energy = 0
            for i in range(32):
                sub_band_energy += ampls_per_freq[sub_band*32 + i]
            # store the summed inst energy in this sub-band
            inst_sub_band_energies.append(sub_band_energy)

        # update sub-band energy histories to include this instant
        for i in range(len(inst_sub_band_energies)):
            self._energy_hist_per_freq_band[i].append(
                inst_sub_band_energies[i]
            )

        # if we have a complete sub-band energy history, compare
        # the values for this 'instant' to the trailing history
        this_inst_is_beat = False
        if len(self._energy_hist_per_freq_band[0]) == 43:

            # compute the average historical energy in the last
            # second, per frequency band
            avg_sub_band_energies = [
                sum(x) / 43 for x in self._energy_hist_per_freq_band
            ]

            # require finding beats in at least 2 bands for this to count
            beat_bands_count = 0
            for inst_nrg, nearby_nrg in zip(
                    inst_sub_band_energies, avg_sub_band_energies):
                if inst_nrg > nearby_nrg * 1.3:
                    beat_bands_count += 1
            if beat_bands_count > 2:
                this_inst_is_beat = True

        # update our trailing beat history deque
        self._beat_history.append(this_inst_is_beat)

    def _run_data_processing(self):
        """
        Threading target to continually read inputted data
        and process it in 1024-sample batches.
        """
        data = [0] * 1024
        idx = 0
        while True:
            data[idx] = self._in_queue.get()
            if idx == 1023:
                self._detect_beat(data)
                self._detect_tempo()
                idx = 0
            else:
                idx += 1

    def add_sample(self, sample):
        """
        Push an audio sample into the Detector's internal
        processing queue.

        Sample should be an iterable of one or more values,
        where each value is the sample value for a single
        audio channel.
        """
        self._in_queue.put(sample)
