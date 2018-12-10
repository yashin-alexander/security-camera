import cv2
import sys
import time 
import numpy
import urllib 
import datetime
from openalpr import Alpr
from subprocess import Popen, PIPE
from difflib import SequenceMatcher
from multiprocessing import Process


DEFAULT_COUNTRY = 'us'
ALPR_CONFIG_PATH = '/etc/openalpr/openalpr.conf'
ALPR_RUNTIME_DATA_PATH = '/usr/share/openalpr/runtime_data'
DEFAULT_CAMERA_DEVICE = '/dev/video0'
IMAGE_NAME = 'image.jpg'
MJPG_STREAM_URL = 'http://0.0.0.0:8080/?action=stream'


class RelayController:
    def __init__(self, gpio_pin):
        self.gpio_pin = gpio_pin
        self.gpio_sysfs_pattern = '/sys/class/gpio/gpio{}/value'.format(gpio_pin)

    @property
    def gpio_state(self):
        with open(self.gpio_sysfs_pattern, "r") as value_file:
            value = value_file.read().strip("\n")
        return value

    @gpio_state.setter
    def gpio_state(self, state):
        with open(self.gpio_sysfs_pattern, "w") as value_file:
            value_file.write(str(state))

    def turn_relay_on(self):
        self.gpio_state = 1

    def turn_relay_off(self):
        self.gpio_state = 0


class LicensePlateSearcher:
    def __init__(self, plate, country=DEFAULT_COUNTRY):
        self.plate = plate
        self.alpr = Alpr(country, ALPR_CONFIG_PATH, ALPR_RUNTIME_DATA_PATH)
        self.trashhold = 0.70
        self.photo_maker = Process(target=self.photogapher, )

    @property
    def _current_time(self):
        now = datetime.datetime.now()
        return "{:>02}:{:>02}:{:>02}".format(now.hour, now.minute, now.second)

    @staticmethod
    def _get_patterns_similarity(pattern_a, pattern_b):
        similarity = SequenceMatcher(None, pattern_a, pattern_b).ratio()
        return round(similarity, 2)

    def _get_plates(self):
        with open('image.jpg', 'rb') as image:
            jpg_bytes = image.read()
        alpr_report = self.alpr.recognize_array(jpg_bytes)
        alpr_results = alpr_report['results']
        plates = [result['plate'] for result in alpr_results]
        return plates

    def _get_plates_validity(self, plates):
        for plate in plates:
            similarity = self._get_patterns_similarity(plate, self.plate)
            if similarity >= self.trashhold:
                return plate
        return None

    def _process_photo(self):
        try:
            plates = self._get_plates()
        except IndexError:
            print "No numbers, at {}".format(self._current_time)
        else:
            valid_plate = self._get_plates_validity(plates)
            if valid_plate is None:
                print "No correct numbers, at {}".format(self._current_time)
            else:
                print "{} at {}".format(valid_plate, self._current_time)

    def photogapher(self):
        stream = urllib.urlopen(MJPG_STREAM_URL)
        stream_fragment = ''
        while True:
            stream_fragment += stream.read(8096)
            photo_start_ptr = stream_fragment.find('\xff\xd8')
            photo_end_ptr = stream_fragment.find('\xff\xd9')
            if photo_start_ptr < photo_end_ptr and photo_start_ptr != -1 and photo_end_ptr != -1:
                jpg = stream_fragment[photo_start_ptr:photo_end_ptr+2]
                stream_fragment = stream_fragment[photo_end_ptr+2:]
                image = cv2.imdecode(numpy.fromstring(jpg, dtype=numpy.uint8), cv2.IMREAD_COLOR)
                cv2.imwrite('image.jpg', image)
            elif photo_end_ptr > photo_start_ptr:
                stream_fragment = ''
            else:
                pass

    def run(self):
        run_command('mjpg_streamer -i "input_uvc.so -d /dev/video0 -r 1280x720 -y 1 -n" -o "output_http.so -p 8080 -w /usr/share/mjpg-streamer/www/"')
        time.sleep(1)
        self.photo_maker.start()
        time.sleep(1)
        while True:
            self._process_photo()


def run_command(command, wait=False):
    subproc = Popen(command, shell=True, stdout=PIPE, stderr=PIPE)
    if wait:
        stdout, stderr = subproc.communicate()
        return stdout.decode(), stderr.decode()


def main():
    try:
        plate = sys.argv[1]
    except IndexError:
        print '"plate pattern" positional parameter required!'
        exit(1)
    plate_searcher = LicensePlateSearcher(plate)
    plate_searcher.run()


if __name__ == '__main__':
    main()
