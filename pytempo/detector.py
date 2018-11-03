import copy

from threading import Thread
from collections import deque, defaultdict
from queue import Queue
from cmath import exp, pi


def fft(x):
    # adapted from here:
    # https://rosettacode.org/wiki/Fast_Fourier_transform#Python
    n = len(x)
    if n <= 1:
        return x
    even = fft(x[0::2])
    odd = fft(x[1::2])
    t = [exp(-2j * pi * k / n) * odd[k] for k in range(n // 2)]
    return [even[k] + t[k] for k in range(n // 2)] + \
           [even[k] - t[k] for k in range(n // 2)]


class TempoDetector(object):
    """
    Data processing class whose instances wrap a thread
    that consumes 16-bit PCM audio data and produces
    BPM estimates for the music therein.

    For a detailed example of how to use this class,
    take a look at this script:
        https://github.com/dcully/pytempo/scripts/detect_tempo
    """
    def __init__(self, publisher, debug=False, fft_impl=None):
        """
        The publisher instance can be any object which
        has a 'publish' method. The 'publish' should
        take one argument, an outputted BPM, to do with as
        it sees fit - print to stdout, publish on a ROS
        topic, etc.

        You can pass in your own fft implementation
        (such as numpy.fft.fft) if you do not want to use
        the included pure-Python implementation (this might
        be beneficial to you for performance reasons).
        """
        self._debug = debug
        self._fft = fft
        if fft_impl is not None:
            self._fft = fft_impl
        self._in_queue = Queue(maxsize=1024)
        self._publisher = publisher
        self._energy_hist_per_freq_band = []
        for _ in range(32):
            self._energy_hist_per_freq_band.append(deque(maxlen=43))
        self._beat_histories = []
        for _ in range(32):
            self._beat_histories.append(deque(maxlen=43*7))
        self._processing_thread = Thread(
            target=self._run_data_processing,
            daemon=True,
        )
        self._processing_thread.start()

    def _gap_to_bpm(self, gap_length):
        """
        Convert a 'gap length' of sequential instantaneous energy
        bins to a BPM value.
        """
        return (1 / (gap_length / 43)) * 60.0

    def _detect_tempo(self, beat_history):
        """
        Look at the beat history and derive a tempo, returning
        a BPM as an int if one is found (None otherwise).
        """

        # wait for a full history before inspecting it
        if not len(beat_history) == 43*7:
            return

        # a gap of 19 is about 136 bpm, and a gap of 35 is about 73 bpm
        # By staying inside these possible bpm values, we avoid
        # issues with BPM doubling/halving (i.e., missing a beat and counting
        # some votes for 60 BPM instead of 120 BPM, skewing our final result
        # downwards)
        # songs outside of this range are rare anyway (at least in pop music)

        # count all relevant gaps
        gap_length_counts = defaultdict(lambda: 0)
        for gap_length in range(19, 35):
            for start in range(0, len(beat_history) - gap_length):
                end = start + gap_length
                if beat_history[start] is True and beat_history[end] is True:
                    gap_length_counts[gap_length] += 1

        # convert each gap we found into a BPM value (one vote per gap)
        bpm_candidates = []
        for gap_length in gap_length_counts.keys():

            # discard BPM candidates for which we only noticed one interval
            if gap_length_counts[gap_length] < 2:
                continue

            for _ in range(gap_length_counts[gap_length]):
                bpm_candidates.append(self._gap_to_bpm(gap_length))

        # if there's not enough data to analyze just give up
        if len(bpm_candidates) < 2:
            return None

        # return the most common BPM
        counts = defaultdict(lambda: 0)
        for bpm in bpm_candidates:
            counts[bpm] += 1
        counts = [(key, counts[key]) for key in counts.keys()]
        counts.sort(key=lambda x: x[1], reverse=True)
        bpm = counts[0][0]

        # ... if it's reasonable :-)
        if 71 < bpm < 139:
            return bpm
        return None

    def _detect_tempos(self):
        """
        Inspect the bottom 16 frequency band deques, deriving a bpm estimate
        from each, and then use those 16 samples to select an overall BPM
        """

        if self._debug and len(self._beat_histories[0]) == 43 * 7:
            # dump out the beat histories across
            # all 32 channels for visual inspection
            for band_idx in range(16):
                my_str = ''
                for e in self._beat_histories[band_idx]:
                    my_str += '1' if e else '0'
                print(my_str)
            print('\n\n')

        # calculate the BPM within each frequency band
        band_bpms = []
        for freq_band_idx in range(16):
            history = list(copy.deepcopy(self._beat_histories[freq_band_idx]))
            band_bpms.append(self._detect_tempo(history))

        # filter out no-signal bands
        band_bpms = [bpm for bpm in band_bpms if bpm is not None]
        if len(band_bpms) == 0:
            return None

        # count frequency of selected BPMs across bands
        counts = defaultdict(lambda: 0)
        for bpm in band_bpms:
            counts[bpm] += 1
        counts = [(key, counts[key]) for key in counts.keys()]
        counts.sort(key=lambda x: x[1], reverse=True)

        # return the most commonly detected BPM across the frequency bands
        return counts[0][0]

    def _detect_beat(self, data):
        """
        Process the raw data to detect beats in this instant, and update
        history accordingly with a True or False value.
        """
        # collapse data into one channel
        data = [sum(d) / len(d) for d in data]

        # compute fft of samples (giving us 1024 complex numbers)
        data = self._fft(data)

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
        if len(self._energy_hist_per_freq_band[0]) == 43:

            # compute the average historical energy in the last
            # second, per frequency band
            avg_sub_band_energies = [
                sum(x) / 43 for x in self._energy_hist_per_freq_band
            ]

            # record beats found across the 16 lower bands
            for band_idx in range(16):
                inst_nrg = inst_sub_band_energies[band_idx]
                avg_nrg = avg_sub_band_energies[band_idx]
                beat_found = False
                if inst_nrg > avg_nrg * 1.3:
                    beat_found = True
                self._beat_histories[band_idx].append(beat_found)

    def _run_data_processing(self):
        """
        Threading target to continually read inputted data
        and process it in 1024-sample batches.
        """
        data = [0] * 1024
        idx = 0

        if self._debug:
            import time
            count = 0
            start_ts = time.time()

        while True:
            data[idx] = self._in_queue.get()

            if self._debug:
                count += 1

            if idx == 1023:
                self._detect_beat(data)
                bpm = self._detect_tempos()
                self._publisher.publish(bpm)
                idx = 0
            else:
                idx += 1

            if self._debug and count % 44100 == 0:
                print('processed {} seconds of data in '
                      '{} seconds'
                      .format(count / 44100,
                              time.time() - start_ts))

    def add_sample(self, sample):
        """
        Push an audio sample into the Detector's internal
        processing queue.

        Sample should be an iterable of one or more values,
        where each value is the sample value for a single
        audio channel.
        """
        self._in_queue.put(sample)
