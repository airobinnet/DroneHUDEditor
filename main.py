import sys
import cv2
import re
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                            QSlider, QCheckBox, QProgressDialog, QMessageBox,
                            QComboBox)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QIcon
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import math
from multiprocessing import Pool, cpu_count
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtCore import QUrl
import bisect
import csv
from io import StringIO
import time
from themes import Themes, Theme
from hud_elements import HUDRenderer
from moviepy.editor import VideoFileClip
import tempfile
import pygame.mixer
import os

class TelemetryParser:
    """Parses DJI telemetry data from SRT files into structured format"""
    
    def __init__(self):
        self.data = []
        self.metadata = {
            'filename': '',
            'stats': {
                'GPS': {'LATITUDE': {'min': float('inf'), 'max': -float('inf')},
                       'LONGITUDE': {'min': float('inf'), 'max': -float('inf')}},
                'SPEED': {'TWOD': {'min': float('inf'), 'max': -float('inf')},
                         'THREED': {'min': float('inf'), 'max': -float('inf')},
                         'VERTICAL': {'min': float('inf'), 'max': -float('inf')}},
                'ALTITUDE': {'min': float('inf'), 'max': -float('inf')},
                'BAROMETER': {'min': float('inf'), 'max': -float('inf')},
                'DISTANCE': 0,
                'DURATION': 0,
                'DATE': None
            }
        }
        self.heading_buffer_size = 15  # Number of frames to average
        self.heading_buffer = []  # Buffer for heading values

    def parse_srt(self, srt_text, filename):
        """Parse SRT file contents into telemetry data"""
        self.metadata['filename'] = filename
        
        # Split into blocks
        blocks = srt_text.strip().split('\n\n')
        
        # Process each block
        for block in blocks:
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
                
            # Parse the telemetry line
            telemetry_line = '\n'.join(lines[2:])
            packet = self._parse_telemetry_line(telemetry_line)
            
            if packet:
                self.data.append(packet)
                self._update_stats(packet)
        
        # Calculate derived stats
        self._calculate_derived_stats()
        
        return self

    def _parse_telemetry_line(self, line):
        """Parse a single telemetry line into structured data"""
        # Initialize packet with default values
        packet = {
            'FRAMECNT': 0,
            'DATE': None,
            'ISO': 0,
            'SHUTTER': 0,
            'FNUM': 0,
            'EV': 0,
            'FOCAL_LEN': 0,
            'GPS': {
                'LATITUDE': 0,
                'LONGITUDE': 0
            },
            'ALTITUDE': 0,
            'BAROMETER': 0,
            'CT': 0,
            'HEADING': 0,
            'SPEED': {
                'TWOD': 0,
                'THREED': 0,
                'VERTICAL': 0
            },
            'DISTANCE': 0
        }
        
        # Remove font tags
        line = re.sub(r'<[^>]+>', '', line)
        
        # Extract frame count and timestamp
        frame_match = re.search(r'FrameCnt:\s*(\d+)', line)
        if frame_match:
            packet['FRAMECNT'] = int(frame_match.group(1))
            
        timestamp_match = re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}', line)
        if timestamp_match:
            packet['DATE'] = datetime.strptime(timestamp_match.group(), '%Y-%m-%d %H:%M:%S.%f')
            
        # Extract bracketed values
        for match in re.finditer(r'\[([^\]]+)\]', line):
            content = match.group(1).strip()
            if ':' in content:
                key, value = content.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                try:
                    if key == 'iso':
                        packet['ISO'] = int(value)
                    elif key == 'shutter':
                        if '/' in value:
                            num, den = map(float, value.split('/'))
                            packet['SHUTTER'] = num / den
                        else:
                            packet['SHUTTER'] = float(value)
                    elif key == 'fnum':
                        packet['FNUM'] = float(value)
                    elif key == 'ev':
                        packet['EV'] = int(value)
                    elif key == 'focal_len':
                        packet['FOCAL_LEN'] = float(value)
                    elif key == 'latitude':
                        packet['GPS']['LATITUDE'] = float(value)
                    elif key == 'longitude':
                        packet['GPS']['LONGITUDE'] = float(value)
                    elif key == 'rel_alt':
                        packet['ALTITUDE'] = float(value.split()[0])
                    elif key == 'abs_alt':
                        packet['BAROMETER'] = float(value.split()[0])
                    elif key == 'ct':
                        packet['CT'] = int(value)
                except (ValueError, IndexError) as e:
                    print(f"Error parsing {key}: {value} - {str(e)}")
                    continue
        
        # Debug print for first few frames
        if packet['FRAMECNT'] < 5:
            print(f"\nParsed Frame {packet['FRAMECNT']}:")
            print(f"Altitude: {packet['ALTITUDE']}")
            print(f"GPS: {packet['GPS']}")
            print(f"Date: {packet['DATE']}")
        
        return packet

    def _update_stats(self, packet):
        """Update running statistics with new packet data"""
        stats = self.metadata['stats']
        
        # Update GPS bounds if GPS data exists
        if 'GPS' in packet and packet['GPS']:
            gps = packet['GPS']
            if 'LATITUDE' in gps:
                stats['GPS']['LATITUDE']['min'] = min(stats['GPS']['LATITUDE']['min'], gps['LATITUDE'])
                stats['GPS']['LATITUDE']['max'] = max(stats['GPS']['LATITUDE']['max'], gps['LATITUDE'])
            if 'LONGITUDE' in gps:
                stats['GPS']['LONGITUDE']['min'] = min(stats['GPS']['LONGITUDE']['min'], gps['LONGITUDE'])
                stats['GPS']['LONGITUDE']['max'] = max(stats['GPS']['LONGITUDE']['max'], gps['LONGITUDE'])
        
        # Update altitude bounds if altitude data exists
        if 'ALTITUDE' in packet and packet['ALTITUDE'] is not None:
            stats['ALTITUDE']['min'] = min(stats['ALTITUDE']['min'], packet['ALTITUDE'])
            stats['ALTITUDE']['max'] = max(stats['ALTITUDE']['max'], packet['ALTITUDE'])
        
        if 'BAROMETER' in packet and packet['BAROMETER'] is not None:
            stats['BAROMETER']['min'] = min(stats['BAROMETER']['min'], packet['BAROMETER'])
            stats['BAROMETER']['max'] = max(stats['BAROMETER']['max'], packet['BAROMETER'])
        
        # Update date range if date exists
        if 'DATE' in packet and packet['DATE']:
            if not stats['DATE']:
                stats['DATE'] = packet['DATE']
            else:
                stats['DATE'] = min(stats['DATE'], packet['DATE'])

    def _calculate_derived_stats(self):
        """Calculate derived statistics like speeds and distances"""
        if len(self.data) < 2:
            return
            
        # Initialize buffers for smoothing
        speed_buffer = []
        vertical_speed_buffer = []
        self.heading_buffer = []  # Initialize heading buffer
        smooth_window = 30  # Increased window size for smoother data
        
        # Gaussian weights for weighted moving average
        def gaussian_weights(window_size):
            x = np.linspace(-2, 2, window_size)
            weights = np.exp(-x**2)
            return weights / weights.sum()
        
        weights = gaussian_weights(smooth_window)
        
        # Calculate speeds and distances between points
        total_distance = 0
        last_valid_heading = 0
        
        for i in range(1, len(self.data)):
            prev = self.data[i-1]
            curr = self.data[i]
            
            # Time difference in seconds
            dt = (curr['DATE'] - prev['DATE']).total_seconds()
            if dt <= 0:
                continue
                
            # Calculate horizontal distance
            dist_2d = self.haversine_distance(
                prev['GPS']['LATITUDE'], prev['GPS']['LONGITUDE'],
                curr['GPS']['LATITUDE'], curr['GPS']['LONGITUDE']
            )
            
            # Calculate vertical distance (using altitude)
            dist_vert = curr['ALTITUDE'] - prev['ALTITUDE']
            
            # Calculate total 3D distance using Pythagorean theorem
            dist_3d = math.sqrt(dist_2d**2 + dist_vert**2)
            total_distance += dist_3d
            
            # Calculate instantaneous speeds
            instant_speed_2d = dist_2d / dt  # m/s
            instant_speed_vert = dist_vert / dt  # m/s
            instant_speed_3d = dist_3d / dt  # m/s

            # Apply reasonable limits
            max_speed = 25  # m/s (90 km/h)
            max_vertical_speed = 8  # m/s
            instant_speed_2d = min(instant_speed_2d, max_speed)
            instant_speed_vert = max(min(instant_speed_vert, max_vertical_speed), 
                                   -max_vertical_speed)
            instant_speed_3d = min(instant_speed_3d, 
                                 math.sqrt(max_speed**2 + max_vertical_speed**2))

            # Apply smoothing using weighted moving average
            speed_buffer.append(instant_speed_2d)
            vertical_speed_buffer.append(instant_speed_vert)
            
            if len(speed_buffer) > smooth_window:
                speed_buffer.pop(0)
                vertical_speed_buffer.pop(0)

            # Calculate weighted averages
            if len(speed_buffer) == smooth_window:
                weighted_speed = np.average(speed_buffer, weights=weights)
                weighted_vert_speed = np.average(vertical_speed_buffer, weights=weights)
            else:
                # Use simple average if buffer not full yet
                weighted_speed = sum(speed_buffer) / len(speed_buffer)
                weighted_vert_speed = sum(vertical_speed_buffer) / len(vertical_speed_buffer)

            # Store smoothed speeds in packet
            curr['SPEED'] = {
                'TWOD': weighted_speed,
                'VERTICAL': weighted_vert_speed,
                'THREED': math.sqrt(weighted_speed**2 + weighted_vert_speed**2)
            }

            # Calculate heading with improved smoothing
            if dist_2d > 0.05:  # Only update heading when moving more than 5cm
                instant_heading = self.calculate_bearing(
                    prev['GPS']['LATITUDE'], prev['GPS']['LONGITUDE'],
                    curr['GPS']['LATITUDE'], curr['GPS']['LONGITUDE']
                )
                
                # Add to heading buffer
                self.heading_buffer.append(instant_heading)
                if len(self.heading_buffer) > self.heading_buffer_size:
                    self.heading_buffer.pop(0)
                
                # Calculate smoothed heading using circular mean
                smoothed_heading = self.calculate_circular_mean(self.heading_buffer)
                last_valid_heading = smoothed_heading
            
            curr['HEADING'] = last_valid_heading
            curr['DISTANCE'] = total_distance

            # Update speed stats
            self._update_speed_stats(curr)

        # Calculate final stats
        self.metadata['stats']['DISTANCE'] = total_distance
        self.metadata['stats']['DURATION'] = (
            self.data[-1]['DATE'] - self.data[0]['DATE']
        ).total_seconds()

    def haversine_distance(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two GPS coordinates in meters"""
        R = 6371000  # Earth radius in meters
        
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        
        a = (math.sin(delta_phi/2)**2 + 
             math.cos(phi1) * math.cos(phi2) * 
             math.sin(delta_lambda/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c

    def to_csv(self):
        """Export telemetry data as CSV"""
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        headers = ['TIMECODE', 'FRAMECNT', 'DATE', 'ISO', 'SHUTTER', 'FNUM', 'EV',
                  'FOCAL_LEN', 'GPS.LATITUDE', 'GPS.LONGITUDE', 'ALTITUDE', 'BAROMETER',
                  'SPEED.TWOD', 'SPEED.VERTICAL', 'SPEED.THREED', 'DISTANCE']
        writer.writerow(headers)
        
        # Write data rows
        for packet in self.data:
            row = [
                packet.get('TIMECODE', ''),
                packet.get('FRAMECNT', ''),
                packet.get('DATE', '').isoformat() if packet.get('DATE') else '',
                packet.get('ISO', ''),
                packet.get('SHUTTER', ''),
                packet.get('FNUM', ''),
                packet.get('EV', ''),
                packet.get('FOCAL_LEN', ''),
                packet['GPS'].get('LATITUDE', ''),
                packet['GPS'].get('LONGITUDE', ''),
                packet.get('ALTITUDE', ''),
                packet.get('BAROMETER', ''),
                packet['SPEED'].get('TWOD', ''),
                packet['SPEED'].get('VERTICAL', ''),
                packet['SPEED'].get('THREED', ''),
                packet.get('DISTANCE', '')
            ]
            writer.writerow(row)
            
        return output.getvalue()

    def calculate_bearing(self, lat1, lon1, lat2, lon2):
        """Calculate bearing between two points in degrees"""
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_lambda = math.radians(lon2 - lon1)

        y = math.sin(delta_lambda) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - \
            math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)

        bearing = math.atan2(y, x)
        bearing = math.degrees(bearing)
        bearing = (bearing + 360) % 360
        return bearing

    def _update_speed_stats(self, packet):
        """Update speed statistics with new packet data"""
        stats = self.metadata['stats']['SPEED']
        
        for speed_type in ['TWOD', 'THREED', 'VERTICAL']:
            speed = packet['SPEED'][speed_type]
            stats[speed_type]['min'] = min(stats[speed_type]['min'], speed)
            stats[speed_type]['max'] = max(stats[speed_type]['max'], speed)

    def calculate_circular_mean(self, angles):
        """Calculate the mean of circular quantities (angles) with better smoothing"""
        if not angles:
            return 0
        
        # Convert angles to radians
        angles_rad = np.deg2rad(angles)
        
        # Calculate mean of sin and cos components with exponential weighting
        weights = np.exp(np.linspace(-1, 0, len(angles)))  # Exponential weights
        weights = weights / weights.sum()  # Normalize weights
        
        mean_sin = np.average(np.sin(angles_rad), weights=weights)
        mean_cos = np.average(np.cos(angles_rad), weights=weights)
        
        # Calculate mean angle
        mean_angle = np.rad2deg(np.arctan2(mean_sin, mean_cos))
        
        # Normalize to 0-360
        return (mean_angle + 360) % 360

class VideoPlayer:
    def __init__(self):
        self.cap = None
        self.video_widget = QLabel()
        self.video_widget.setMinimumSize(800, 600)
        self.current_frame = 0
        self.fps = 0
        self.duration = 0
        self.is_playing = False
        self.frame_buffer = []  # Add frame buffer
        self.buffer_size = 10   # Number of frames to buffer
        self.frame_queue = queue.Queue(maxsize=30)  # Add frame queue
        
        # Create timer for OpenCV playback
        self.timer = QTimer()
        self.timer.timeout.connect(self.display_frame)  # Changed from update_frame
        
        # Initialize HUD renderer
        self.hud_renderer = HUDRenderer()
        self.telemetry_parser = None
        
        # Initialize audio with Sound instead of music
        self.audio_system = None
        try:
            pygame.mixer.init(frequency=44100)
            pygame.mixer.set_num_channels(2)  # Use 2 channels for crossfading
            self.audio_system = 'pygame'
            self.sound = None
            self.sound_channel = None
            self.current_audio_pos = 0
        except Exception as e:
            print(f"Pygame audio init failed: {e}")
        
        self.audio_playing = False
        self.audio = None
        self.volume = 0.5

        # Start frame reading thread
        self.reading_thread = threading.Thread(target=self.read_frames, daemon=True)
        self.reading_active = False
        self.seek_lock = threading.Lock()
        self.seeking = False
        self.force_update = False

        # Add preview video attributes
        self.preview_cap = None
        self.preview_path = None
        self.original_path = None
        self.preview_scale = 0.3  # Scale factor for preview video

    def load_video(self, path):
        self.original_path = path
        
        # Create preview video
        self.create_preview_video(path)
        
        if self.cap is not None:
            self.cap.release()
        
        # Use preview video for playback
        self.cap = cv2.VideoCapture(self.preview_path)
        
        # Set OpenCV buffer size
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 3)
        
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.duration = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) / self.fps * 1000)
        self.timer.setInterval(int(1000 / self.fps))
        self.current_frame = 0
        
        # Clear queue and start reading thread
        while not self.frame_queue.empty():
            self.frame_queue.get()
        
        self.reading_active = True
        self.reading_thread = threading.Thread(target=self.read_frames, daemon=True)
        self.reading_thread.start()
        
        self.display_frame()

    def create_preview_video(self, input_path):
        """Create a lower resolution preview video for smooth playback"""
        try:
            # Create temporary file for preview video
            preview_file = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
            self.preview_path = preview_file.name
            preview_file.close()

            # Open input video
            cap = cv2.VideoCapture(input_path)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # Calculate preview dimensions
            preview_width = int(width * self.preview_scale)
            preview_height = int(height * self.preview_scale)

            # Create video writer with hardware acceleration if available
            # Try different codecs in order of preference
            codecs = [
                ('h264_nvenc', 'mp4v'),  # NVIDIA GPU acceleration
                ('h264_qsv', 'mp4v'),    # Intel Quick Sync
                ('h264_amf', 'mp4v'),    # AMD GPU acceleration
                ('mp4v', 'mp4v')         # Software fallback
            ]

            out = None
            for hw_codec, fallback_codec in codecs:
                try:
                    fourcc = cv2.VideoWriter_fourcc(*hw_codec)
                    out = cv2.VideoWriter(self.preview_path, fourcc, fps, 
                                        (preview_width, preview_height))
                    if out.isOpened():
                        print(f"Using codec: {hw_codec}")
                        break
                except:
                    continue

            if out is None or not out.isOpened():
                # Fallback to default codec
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                out = cv2.VideoWriter(self.preview_path, fourcc, fps, 
                                    (preview_width, preview_height))

            # Create progress dialog
            progress = QProgressDialog("Creating preview video...", "Cancel", 0, 100)
            progress.setWindowModality(Qt.WindowModality.WindowModal)

            # Calculate frame skip for faster processing
            # Process about 30 frames per second of video
            target_frame_count = max(30 * (total_frames / fps), total_frames / 10)
            frame_skip = max(1, int(total_frames / target_frame_count))

            frame_count = 0
            processed_count = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Process only every nth frame
                if frame_count % frame_skip == 0:
                    # Use INTER_AREA for downscaling (better quality and reasonable speed)
                    preview_frame = cv2.resize(frame, (preview_width, preview_height), 
                                            interpolation=cv2.INTER_AREA)
                    out.write(preview_frame)
                    processed_count += 1

                    # Update progress
                    progress_value = int((frame_count / total_frames) * 100)
                    progress.setValue(progress_value)
                    if progress.wasCanceled():
                        break

                frame_count += 1

                # Process events to keep UI responsive
                QApplication.processEvents()

            # Clean up
            cap.release()
            out.release()
            progress.close()

            print(f"Preview created with {processed_count} frames")

            # Verify the preview video was created successfully
            if not os.path.exists(self.preview_path) or os.path.getsize(self.preview_path) == 0:
                print("Preview creation failed, falling back to original video")
                self.preview_path = input_path

        except Exception as e:
            print(f"Error creating preview video: {e}")
            import traceback
            traceback.print_exc()
            self.preview_path = input_path  # Fallback to original video

    def read_frames(self):
        while self.reading_active and self.cap is not None:
            # Skip frame reading if seeking or force updating
            if self.seeking or self.force_update:
                time.sleep(0.001)
                continue
            
            with self.seek_lock:
                if self.frame_queue.qsize() < self.frame_queue.maxsize:
                    ret, frame = self.cap.read()
                    if ret:
                        # Resize frame for display
                        display_width = 1280
                        display_height = int(frame.shape[0] * (display_width / frame.shape[1]))
                        frame_display = cv2.resize(frame, (display_width, display_height))
                        
                        # Add HUD if available
                        if self.hud_renderer and self.telemetry_parser and self.telemetry_parser.data:
                            telemetry_data = self.get_telemetry_data_for_frame(self.current_frame)
                            if telemetry_data:
                                frame_display = self.hud_renderer.render(frame_display, telemetry_data)
                        
                        self.frame_queue.put((self.current_frame, frame_display))
                    else:
                        self.reading_active = False
                        break
                else:
                    time.sleep(0.001)  # Small delay to prevent CPU overuse

    def display_frame(self):
        if not self.frame_queue.empty():
            frame_number, frame = self.frame_queue.get()
            
            # Convert frame to QImage for display
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_frame.shape
            bytes_per_line = ch * w
            qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            self.video_widget.setPixmap(QPixmap.fromImage(qt_image))
            
            self.current_frame += 1

    def get_telemetry_data_for_frame(self, frame_number):
        """Get telemetry data for the current frame"""
        if not self.telemetry_parser or not self.telemetry_parser.data:
            return None
            
        # Find the telemetry packet with matching frame number
        for packet in self.telemetry_parser.data:
            if packet['FRAMECNT'] == frame_number:
                return packet
                
        # If no exact match, find the closest previous frame
        closest_packet = None
        for packet in self.telemetry_parser.data:
            if packet['FRAMECNT'] <= frame_number:
                if not closest_packet or packet['FRAMECNT'] > closest_packet['FRAMECNT']:
                    closest_packet = packet
                    
        return closest_packet

    def set_telemetry_parser(self, parser):
        """Set the telemetry parser instance"""
        self.telemetry_parser = parser

    def get_position(self):
        """Get current playback position in milliseconds"""
        if self.cap is not None:
            return int(self.current_frame / self.fps * 1000)
        return 0
        
    def get_duration(self):
        """Get video duration in milliseconds"""
        return self.duration
        
    def seek(self, position):
        """Seek to position in milliseconds"""
        if self.cap is not None:
            # Pause playback during seek
            was_playing = self.is_playing
            self.pause()
            
            with self.seek_lock:
                self.seeking = True
                
                # Clear the frame queue
                while not self.frame_queue.empty():
                    self.frame_queue.get()
                
                # Calculate target frame
                frame = int(position / 1000.0 * self.fps)
                self.current_frame = frame
                
                # Seek to nearest keyframe
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
                
                # Read a few frames to stabilize seeking
                for _ in range(3):
                    self.cap.read()
                
                # Reset audio position
                if self.audio and self.sound:
                    try:
                        if self.sound_channel and self.sound_channel.get_busy():
                            self.sound_channel.stop()
                        self.current_audio_pos = position / 1000.0
                        if was_playing:
                            samples_per_sec = 44100
                            skip_samples = int(self.current_audio_pos * samples_per_sec)
                            sound_array = pygame.sndarray.array(self.sound)
                            if skip_samples < len(sound_array):
                                new_array = sound_array[skip_samples:]
                                new_sound = pygame.sndarray.make_sound(new_array)
                                new_sound.set_volume(self.volume)
                                self.sound_channel.play(new_sound)
                                self.audio_playing = True
                    except Exception as e:
                        print(f"Audio seek error: {e}")
                
                # Read and display the new frame
                ret, frame = self.cap.read()
                if ret:
                    self.display_frame_direct(frame)
                
                # Restart frame reading thread
                self.reading_active = True
                if not self.reading_thread.is_alive():
                    self.reading_thread = threading.Thread(target=self.read_frames, daemon=True)
                    self.reading_thread.start()
                
                self.seeking = False
            
            # Resume playback if it was playing before
            if was_playing:
                self.play()

    def display_frame_direct(self, frame):
        """Display a frame directly without queuing"""
        # Resize frame for display
        display_width = 1280
        display_height = int(frame.shape[0] * (display_width / frame.shape[1]))
        frame_display = cv2.resize(frame, (display_width, display_height))
        
        # Add HUD if available
        if self.hud_renderer and self.telemetry_parser and self.telemetry_parser.data:
            telemetry_data = self.get_telemetry_data_for_frame(self.current_frame)
            if telemetry_data:
                frame_display = self.hud_renderer.render(frame_display, telemetry_data)
        
        # Convert to QImage and display
        rgb_frame = cv2.cvtColor(frame_display, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.video_widget.setPixmap(QPixmap.fromImage(qt_image))

    def play(self):
        """Start playback"""
        if self.cap is not None:
            # Ensure reading thread is active
            if not self.reading_active or not self.reading_thread.is_alive():
                self.reading_active = True
                self.reading_thread = threading.Thread(target=self.read_frames, daemon=True)
                self.reading_thread.start()
            
            self.is_playing = True
            self.timer.start()
            
            # Start audio playback
            if self.audio and self.sound and self.sound_channel:
                try:
                    if not self.sound_channel.get_busy():
                        # Calculate how much of the sound to skip
                        samples_per_sec = 44100
                        skip_samples = int(self.current_audio_pos * samples_per_sec)
                        
                        # Create a new Sound object starting from the current position
                        sound_array = pygame.sndarray.array(self.sound)
                        if skip_samples < len(sound_array):
                            new_array = sound_array[skip_samples:]
                            new_sound = pygame.sndarray.make_sound(new_array)
                            new_sound.set_volume(self.volume)
                            self.sound_channel.play(new_sound)
                    else:
                        self.sound_channel.unpause()
                    
                    self.audio_playing = True
                except Exception as e:
                    print(f"Audio playback error: {e}")

    def pause(self):
        """Pause playback"""
        self.is_playing = False
        self.timer.stop()
        # Pause audio playback
        if self.audio and self.audio_playing and self.sound_channel:
            try:
                if self.sound_channel.get_busy():
                    self.sound_channel.pause()  # Use pause instead of stop
                    self.audio_playing = False
            except:
                pass

    def close(self):
        """Clean up resources"""
        self.reading_active = False
        if self.reading_thread.is_alive():
            self.reading_thread.join()
        self.timer.stop()
        if self.cap is not None:
            self.cap.release()
        if self.preview_cap is not None:
            self.preview_cap.release()
        # Delete preview video file
        if self.preview_path and os.path.exists(self.preview_path):
            try:
                os.unlink(self.preview_path)
            except:
                pass
        if self.audio:
            try:
                if self.audio_system == 'pygame':
                    pygame.mixer.music.stop()
                    pygame.mixer.quit()
                elif self.audio_system == 'qt':
                    self.media_player.stop()
            except:
                pass

    def set_hud(self, hud_renderer, telemetry_data):
        """Set the HUD renderer and telemetry data"""
        self.hud_renderer = hud_renderer
        # Convert old telemetry data format to new format if needed
        if isinstance(telemetry_data, dict):
            self.telemetry_parser = TelemetryParser()
            self.telemetry_parser.data = []
            for frame_num, data in telemetry_data.items():
                # Convert old format to new format
                packet = {
                    'FRAMECNT': frame_num,
                    'ISO': data.iso,
                    'SHUTTER': data.shutter,
                    'FNUM': data.fnum,
                    'EV': data.ev,
                    'FOCAL_LEN': data.focal_length,
                    'GPS': {
                        'LATITUDE': data.latitude,
                        'LONGITUDE': data.longitude
                    },
                    'ALTITUDE': data.rel_altitude,
                    'BAROMETER': data.abs_altitude,
                    'CT': data.ct,
                    'SPEED': {
                        'TWOD': data.speed,
                        'VERTICAL': data.vertical_speed,
                        'THREED': math.sqrt(data.speed**2 + data.vertical_speed**2)
                    },
                    'heading': data.heading
                }
                self.telemetry_parser.data.append(packet)
        else:
            self.telemetry_parser = telemetry_data

    def update_frame(self):
        """Force an update of the current frame (for HUD changes)"""
        self.force_update = True
        # Clear queue to force a fresh frame
        with self.seek_lock:
            while not self.frame_queue.empty():
                self.frame_queue.get()
            
            # Re-read current frame
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
            ret, frame = self.cap.read()
            if ret:
                # Resize frame for display
                display_width = 1280
                display_height = int(frame.shape[0] * (display_width / frame.shape[1]))
                frame_display = cv2.resize(frame, (display_width, display_height))
                
                # Add HUD if available
                if self.hud_renderer and self.telemetry_parser and self.telemetry_parser.data:
                    telemetry_data = self.get_telemetry_data_for_frame(self.current_frame)
                    if telemetry_data:
                        frame_display = self.hud_renderer.render(frame_display, telemetry_data)
                
                # Convert and display frame
                rgb_frame = cv2.cvtColor(frame_display, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                self.video_widget.setPixmap(QPixmap.fromImage(qt_image))
        
        self.force_update = False

    def set_volume(self, volume):
        """Set audio volume (0.0 to 1.0)"""
        self.volume = volume
        if self.audio and self.sound:
            try:
                # Update volume for the currently playing sound
                if self.sound_channel and self.sound_channel.get_busy():
                    current_sound = self.sound_channel.get_sound()
                    if current_sound:
                        current_sound.set_volume(volume)
                # Also update the original sound's volume
                self.sound.set_volume(volume)
            except Exception as e:
                print(f"Volume change error: {e}")

    def load_music(self, path):
        """Load a music file for playback"""
        if self.audio_system == 'pygame':
            try:
                # Stop any currently playing sound
                if self.sound_channel and self.sound_channel.get_busy():
                    self.sound_channel.stop()
                
                self.sound = pygame.mixer.Sound(path)
                self.sound_channel = pygame.mixer.Channel(0)
                self.sound.set_volume(self.volume)
                self.audio = True
                self.current_audio_pos = 0  # Reset position
                self.audio_playing = False
                return True
            except Exception as e:
                print(f"Could not load music with pygame: {e}")

        self.audio = None
        return False

    def update_volume_icon(self, value):
        """Update the volume icon based on the current volume"""
        if value == 0:
            self.volume_btn.setText("🔇")  # Muted
        elif value < 33:
            self.volume_btn.setText("🔈")  # Low volume
        elif value < 66:
            self.volume_btn.setText("🔉")  # Medium volume
        else:
            self.volume_btn.setText("🔊")  # High volume

    def toggle_mute(self):
        """Toggle audio mute state"""
        if not hasattr(self, 'last_volume'):
            self.last_volume = 50

        if self.volume_slider.value() == 0:
            self.volume_slider.setValue(self.last_volume)
        else:
            self.last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)

class VideoExporter(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, input_path, output_path, telemetry_data, hud_renderer, 
                 start_frame=0, end_frame=None, music_path=None):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.telemetry_data = telemetry_data
        self.hud_renderer = hud_renderer
        self.start_frame = start_frame
        self.end_frame = end_frame
        self.music_path = music_path
        self.cancelled = False
        
        # Create frame number to telemetry lookup dict
        self.telemetry_lookup = {data['FRAMECNT']: data for data in telemetry_data}

    def run(self):
        try:
            # Load video using MoviePy
            video = VideoFileClip(self.input_path)
            fps = video.fps
            
            if self.end_frame is None:
                self.end_frame = int(video.duration * fps)
            
            # Create a subclip if needed
            start_time = self.start_frame / fps
            end_time = self.end_frame / fps
            if start_time > 0 or end_time < video.duration:
                video = video.subclip(start_time, end_time)

            # Create HUD overlay function with correct signature
            def add_hud(get_frame, t):
                frame = get_frame(t)
                frame_num = int(t * fps) + self.start_frame
                telemetry_data = self.telemetry_lookup.get(frame_num)
                
                if telemetry_data:
                    # Convert frame to BGR for OpenCV
                    frame_bgr = frame[:, :, ::-1].copy()
                    # Apply HUD
                    frame_with_hud = self.hud_renderer.render(frame_bgr, telemetry_data)
                    # Convert back to RGB for MoviePy
                    return frame_with_hud[:, :, ::-1]
                return frame

            # Create output video with HUD
            video_with_hud = video.fl(add_hud)

            # Handle music if provided
            if self.music_path:
                from moviepy.editor import AudioFileClip
                # Load the music file
                music = AudioFileClip(self.music_path)
                
                # If music is longer than video, cut it
                if music.duration > video_with_hud.duration:
                    music = music.subclip(0, video_with_hud.duration)
                
                # Add fade out at the end (last 3 seconds)
                fade_duration = min(3, music.duration)
                music = music.audio_fadeout(fade_duration)
                
                # Set the music as the audio for the video
                video_with_hud = video_with_hud.set_audio(music)

            # Use a temporary file for better performance
            temp_output = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name

            # Create progress logger
            from proglog import ProgressBarLogger

            class MyProgressBar(ProgressBarLogger):
                def __init__(self, progress_signal):
                    super().__init__()
                    self.progress_signal = progress_signal
                    self.last_t = 0
                    self.total_time = 0
                
                def bars_callback(self, bar, attr, value, old_value=None):
                    if bar == "t":  # "t" is the main moviepy progress bar
                        if attr == "total":
                            self.total_time = value
                        elif attr == "index":
                            if self.total_time > 0:
                                progress = int((value / self.total_time) * 100)
                                self.progress_signal.emit(progress)
                
                def callback(self, **changes):
                    pass

            # Create progress logger
            my_progress_bar = MyProgressBar(self.progress)

            # Export with optimal settings
            video_with_hud.write_videofile(
                temp_output,
                codec='libx264',
                audio_codec='aac',
                fps=fps,
                preset='fast',
                threads=max(1, cpu_count() - 1),
                bitrate='20000k',
                logger=my_progress_bar,
                ffmpeg_params=[
                    '-crf', '18',
                    '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart'
                ]
            )

            # Move temp file to final destination
            import shutil
            shutil.move(temp_output, self.output_path)

            # Clean up
            video.close()
            video_with_hud.close()
            if self.music_path:
                music.close()

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))
            import traceback
            traceback.print_exc()

class DroneHUDApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Drone HUD Editor")
        self.setGeometry(100, 100, 1200, 800)
        
        self.video_path = None
        self.srt_path = None
        self.video_player = VideoPlayer()
        self.telemetry_data = {}
        
        # Initialize HUD renderer
        self.hud_renderer = self.video_player.hud_renderer
        
        # Add timer for updating time display
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_time_display)
        self.update_timer.start(100)  # Update every 100ms
        
        # Initialize media player
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.5)  # Set default volume to 50%
        
        # Add volume control
        self.volume_slider = None
        
        self.init_ui()
        
    def init_ui(self):
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create a container widget for video and overlay
        video_container = QWidget()
        container_layout = QVBoxLayout(video_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center the video widget
        
        # Add video widget
        container_layout.addWidget(self.video_player.video_widget)
        
        # Add video container to main layout
        layout.addWidget(video_container)
        
        # Add HUD controls
        hud_controls_layout = QHBoxLayout()
        
        self.preview_checkbox = QCheckBox("Show HUD")
        self.preview_checkbox.setChecked(True)
        self.preview_checkbox.stateChanged.connect(self.toggle_hud_preview)
        
        self.iso_checkbox = QCheckBox("ISO")
        self.iso_checkbox.setChecked(True)
        self.iso_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('iso'))
        
        self.shutter_checkbox = QCheckBox("Shutter")
        self.shutter_checkbox.setChecked(True)
        self.shutter_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('shutter'))
        
        self.coords_checkbox = QCheckBox("Coordinates")
        self.coords_checkbox.setChecked(True)
        self.coords_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('coords'))
        
        self.altitude_checkbox = QCheckBox("Altitude")
        self.altitude_checkbox.setChecked(True)
        self.altitude_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('altitude'))
        
        self.crosshair_checkbox = QCheckBox("Crosshair")
        self.crosshair_checkbox.setChecked(True)
        self.crosshair_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('crosshair'))
        
        self.compass_checkbox = QCheckBox("Compass")
        self.compass_checkbox.setChecked(True)
        self.compass_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('compass'))
        
        self.speedometer_checkbox = QCheckBox("Speedometer")
        self.speedometer_checkbox.setChecked(True)
        self.speedometer_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('speedometer'))
        
        self.map_checkbox = QCheckBox("Map")
        self.map_checkbox.setChecked(True)
        self.map_checkbox.stateChanged.connect(lambda: self.toggle_hud_element('map'))
        
        self.horizontal_compass_checkbox = QCheckBox("Horizontal Compass")
        self.horizontal_compass_checkbox.setChecked(True)
        self.horizontal_compass_checkbox.stateChanged.connect(
            lambda: self.toggle_hud_element('horizontal_compass'))
        
        hud_controls_layout.addWidget(self.preview_checkbox)
        hud_controls_layout.addWidget(self.iso_checkbox)
        hud_controls_layout.addWidget(self.shutter_checkbox)
        hud_controls_layout.addWidget(self.coords_checkbox)
        hud_controls_layout.addWidget(self.altitude_checkbox)
        hud_controls_layout.addWidget(self.crosshair_checkbox)
        hud_controls_layout.addWidget(self.compass_checkbox)
        hud_controls_layout.addWidget(self.speedometer_checkbox)
        hud_controls_layout.addWidget(self.map_checkbox)
        hud_controls_layout.addWidget(self.horizontal_compass_checkbox)
        
        # Add speedometer settings
        speed_settings_layout = QHBoxLayout()
        speed_label = QLabel("Max Speed (km/h):")
        self.speed_combo = QComboBox()
        speed_options = [30, 40, 50, 60, 70, 80, 90]
        for speed in speed_options:
            self.speed_combo.addItem(str(speed))
        self.speed_combo.setCurrentText("50")  # Default value
        self.speed_combo.currentTextChanged.connect(self.change_max_speed)
        
        speed_settings_layout.addWidget(speed_label)
        speed_settings_layout.addWidget(self.speed_combo)
        speed_settings_layout.addStretch()
        
        # Add to main layout (after hud_controls_layout)
        layout.addLayout(speed_settings_layout)
        
        # Add theme selector
        theme_layout = QHBoxLayout()
        theme_label = QLabel("Theme:")
        self.theme_combo = QComboBox()
        for theme in Themes:
            self.theme_combo.addItem(theme.value.name)
        self.theme_combo.currentIndexChanged.connect(self.change_theme)
        
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        
        # Create markers layout
        markers_layout = QHBoxLayout()
        
        # Add marker controls
        self.start_marker_btn = QPushButton("Set Start")
        self.end_marker_btn = QPushButton("Set End")
        self.start_marker_btn.clicked.connect(self.set_start_marker)
        self.end_marker_btn.clicked.connect(self.set_end_marker)
        
        self.start_time_label = QLabel("Start: --:--:--")
        self.end_time_label = QLabel("End: --:--:--")
        
        # Initialize marker positions
        self.start_marker = 0
        self.end_marker = None
        
        markers_layout.addWidget(self.start_marker_btn)
        markers_layout.addWidget(self.start_time_label)
        markers_layout.addWidget(self.end_marker_btn)
        markers_layout.addWidget(self.end_time_label)
        markers_layout.addStretch()
        
        # Create controls
        controls_layout = QHBoxLayout()
        
        # Add play/pause button
        self.play_pause_btn = QPushButton("Play")
        self.play_pause_btn.clicked.connect(self.toggle_playback)
        
        # File controls
        self.load_video_btn = QPushButton("Load Video")
        self.load_video_btn.clicked.connect(self.load_video)
        self.load_srt_btn = QPushButton("Load SRT")
        self.load_srt_btn.clicked.connect(self.load_srt)
        self.load_music_btn = QPushButton("Load Music")  # Add music button
        self.load_music_btn.clicked.connect(self.load_music)

        # Time display
        self.time_label = QLabel("00:00:00")

        # Slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self.slider_changed)

        # Export control
        self.export_btn = QPushButton("Export")
        self.export_btn.clicked.connect(self.export_video)

        # Add controls to layout
        controls_layout.addWidget(self.play_pause_btn)
        controls_layout.addWidget(self.load_video_btn)
        controls_layout.addWidget(self.load_srt_btn)
        controls_layout.addWidget(self.load_music_btn)  # Add music button to layout
        controls_layout.addWidget(self.time_label)
        controls_layout.addWidget(self.slider)
        controls_layout.addWidget(self.export_btn)
        
        # Add all layouts to main layout
        layout.addLayout(hud_controls_layout)
        layout.addLayout(theme_layout)
        layout.addLayout(markers_layout)  # Add markers layout
        layout.addLayout(controls_layout)

        # Add volume control layout with icon
        volume_layout = QHBoxLayout()
        
        # Add volume icon button
        self.volume_btn = QPushButton()
        self.volume_btn.setFixedSize(24, 24)
        self.volume_btn.clicked.connect(self.toggle_mute)
        
        volume_label = QLabel("Volume:")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.change_volume)
        
        volume_layout.addWidget(self.volume_btn)
        volume_layout.addWidget(volume_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addStretch()
        
        # Update volume icon
        self.update_volume_icon(50)
        
        # Add volume layout to main layout (after controls_layout)
        layout.addLayout(volume_layout)

    def toggle_playback(self):
        if self.video_player.is_playing:
            self.video_player.pause()
            self.media_player.pause()
            self.play_pause_btn.setText("Play")
        else:
            self.video_player.play()
            self.media_player.play()
            self.play_pause_btn.setText("Pause")

    def slider_changed(self, value):
        if self.video_player:
            self.video_player.seek(value)
            # Sync audio position (convert milliseconds to microseconds)
            self.media_player.setPosition(value)

    def change_volume(self, value):
        """Change the audio volume"""
        volume = value / 100.0
        self.video_player.set_volume(volume)
        self.update_volume_icon(value)
        if hasattr(self, 'last_volume'):
            self.last_volume = value

    def load_video(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Video File", "", 
                                                 "Video Files (*.mp4 *.avi)")
        if file_name:
            self.video_path = file_name
            self.video_player.load_video(file_name)
            self.slider.setMaximum(self.video_player.get_duration())
            
            # Load video audio
            self.media_player.setSource(QUrl.fromLocalFile(file_name))
            
            # Resize window to fit video
            self.resize_window_to_video()
            
            # Try to load matching SRT file
            self.try_load_matching_srt(file_name)

    def resize_window_to_video(self):
        if not self.video_player.cap:
            return
            
        # Get video dimensions
        video_width = int(self.video_player.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = int(self.video_player.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Get screen dimensions
        screen = QApplication.primaryScreen().geometry()
        
        # Calculate maximum video size that fits on screen
        max_width = int(screen.width() * 0.8)  # Use 80% of screen width
        max_height = int(screen.height() * 0.8)  # Use 80% of screen height
        
        # Calculate scaling factor to fit video within max dimensions
        # Account for controls height
        controls_height = 150  # Approximate height of controls
        available_height = max_height - controls_height
        
        # Calculate scale while maintaining aspect ratio
        scale = min(max_width / video_width, available_height / video_height)
        
        # Calculate new dimensions
        new_width = int(video_width * scale)
        new_height = int(video_height * scale)
        
        # Set video widget size
        self.video_player.video_widget.setFixedSize(new_width, new_height)
        
        # Let the window adjust to the new video size
        self.adjustSize()
        
        # Center window on screen
        qr = self.frameGeometry()
        cp = screen.center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())

    def center_window(self):
        # Get the screen geometry
        screen = QApplication.primaryScreen().geometry()
        
        # Calculate center position
        center_x = (screen.width() - self.width()) // 2
        center_y = (screen.height() - self.height()) // 2
        
        # Move window to center
        self.move(center_x, center_y)

    def update_time_display(self):
        if self.video_player:
            position = self.video_player.get_position()
            duration = self.video_player.get_duration()
            
            # Update slider without triggering value changed
            self.slider.blockSignals(True)
            self.slider.setValue(position)
            self.slider.blockSignals(False)
            
            # Update time label
            time_str = self.format_timestamp(position / 1000.0)
            total_time = self.format_timestamp(duration / 1000.0)
            self.time_label.setText(f"{time_str} / {total_time}")
    
    def slider_changed(self, value):
        if self.video_player:
            self.video_player.seek(value)
    
    def load_srt(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open SRT File", "", 
                                                 "SRT Files (*.srt)")
        if file_name:
            self.srt_path = file_name
            self.load_telemetry_data()
            # Update frame to show HUD with new telemetry data
            self.update_frame()

    def closeEvent(self, event):
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        if self.video_player:
            self.video_player.close()
        if self.media_player:
            self.media_player.stop()
        super().closeEvent(event)

    def export_video(self):
        if not self.video_path:
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Video", 
            "", 
            "Video Files (*.mp4)"
        )
        
        if output_path:
            if not output_path.lower().endswith('.mp4'):
                output_path += '.mp4'
            
            music_path = None
            if hasattr(self, 'music_path'):
                # Ask if user wants to use the pre-loaded music
                reply = QMessageBox.question(
                    self, 
                    'Use Loaded Music', 
                    'Would you like to use the pre-loaded music file?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    music_path = self.music_path
                else:
                    # Ask if they want to select a different music file
                    reply = QMessageBox.question(
                        self, 
                        'Select Music', 
                        'Would you like to select a different music file?',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        new_music_path, _ = QFileDialog.getOpenFileName(
                            self,
                            "Select Music File",
                            "",
                            "Audio Files (*.mp3 *.wav *.m4a)"
                        )
                        if new_music_path:
                            music_path = new_music_path
            else:
                # Ask if they want to add music
                reply = QMessageBox.question(
                    self, 
                    'Add Music', 
                    'Would you like to add background music to the video?',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    music_path, _ = QFileDialog.getOpenFileName(
                        self,
                        "Select Music File",
                        "",
                        "Audio Files (*.mp3 *.wav *.m4a)"
                    )
            
            # Use markers for export range
            start_frame = int((self.start_marker / 1000.0) * self.video_player.fps)
            end_frame = None
            if self.end_marker is not None:
                end_frame = int((self.end_marker / 1000.0) * self.video_player.fps)
            
            # Create progress dialog
            progress = QProgressDialog("Exporting video...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            
            # Create and start exporter
            self.exporter = VideoExporter(
                self.video_path, 
                output_path, 
                self.video_player.telemetry_parser.data,
                self.hud_renderer,
                start_frame,
                end_frame,
                music_path
            )
            
            self.exporter.progress.connect(progress.setValue)
            self.exporter.finished.connect(
                lambda: QMessageBox.information(self, "Export Complete", 
                                             f"Video exported successfully to:\n{output_path}")
            )
            self.exporter.error.connect(
                lambda msg: QMessageBox.critical(self, "Export Error", 
                                              f"Error during export: {msg}")
            )

            progress.canceled.connect(self.exporter.terminate)
            self.exporter.start()

    def load_telemetry_data(self):
        if not self.srt_path:
            return
            
        try:
            with open(self.srt_path, 'r', encoding='utf-8') as file:
                content = file.read()
                
            # Create telemetry parser and parse data
            parser = TelemetryParser()
            parser.parse_srt(content, self.srt_path)
            
            # Update video player with parsed data
            self.video_player.telemetry_parser = parser
            
            # Create progress dialog
            progress = QProgressDialog("Pre-rendering map tiles...", "Cancel", 0, 100, self)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)  # Show immediately
            progress.setValue(0)
            
            # Pre-process telemetry data for maps with progress updates
            def progress_callback(percent):
                progress.setValue(int(percent))
                QApplication.processEvents()  # Keep UI responsive
                return not progress.wasCanceled()  # Return False to cancel
                
            self.hud_renderer.preprocess_telemetry(parser.data, progress_callback)
            
            progress.close()
            print(f"Loaded telemetry data for {len(parser.data)} frames")
            
        except Exception as e:
            print(f"Error loading telemetry data: {e}")

    def toggle_hud_preview(self, state):
        """Toggle HUD preview on/off"""
        self.hud_renderer.show_preview = bool(state)
        if self.video_player:
            self.video_player.update_frame()

    def toggle_hud_element(self, element):
        """Toggle HUD elements and update display"""
        if element == 'iso':
            self.hud_renderer.show_iso = self.iso_checkbox.isChecked()
        elif element == 'shutter':
            self.hud_renderer.show_shutter = self.shutter_checkbox.isChecked()
        elif element == 'coords':
            self.hud_renderer.show_coords = self.coords_checkbox.isChecked()
        elif element == 'altitude':
            self.hud_renderer.show_altitude = self.altitude_checkbox.isChecked()
        elif element == 'crosshair':
            self.hud_renderer.show_crosshair = self.crosshair_checkbox.isChecked()
        elif element == 'compass':
            self.hud_renderer.show_compass = self.compass_checkbox.isChecked()
        elif element == 'speedometer':
            self.hud_renderer.show_speedometer = self.speedometer_checkbox.isChecked()
        elif element == 'map':
            self.hud_renderer.show_map = self.map_checkbox.isChecked()
        elif element == 'horizontal_compass':
            self.hud_renderer.show_horizontal_compass = self.horizontal_compass_checkbox.isChecked()
        
        # Update the current frame to show changes
        if self.video_player:
            self.video_player.update_frame()

    def try_load_matching_srt(self, video_path):
        # Try both .srt and .SRT extensions
        for ext in ['.srt', '.SRT']:
            srt_path = video_path.rsplit('.', 1)[0] + ext
            try:
                with open(srt_path, 'r', encoding='utf-8') as f:
                    self.srt_path = srt_path
                    print(f"Found matching SRT file: {srt_path}")
                    self.load_telemetry_data()
                    return True
            except FileNotFoundError:
                continue
        return False

    def format_timestamp(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def change_theme(self, index):
        """Change the HUD theme"""
        theme = list(Themes)[index].value
        self.hud_renderer.set_theme(theme)
        if self.video_player:
            self.video_player.update_frame()

    def set_start_marker(self):
        """Set start marker at current position"""
        if self.video_player:
            self.start_marker = self.video_player.get_position()
            self.start_time_label.setText(f"Start: {self.format_timestamp(self.start_marker/1000.0)}")
            # Ensure end marker is after start marker
            if self.end_marker is not None and self.end_marker <= self.start_marker:
                self.end_marker = None
                self.end_time_label.setText("End: --:--:--")
            self.update_slider_style()

    def set_end_marker(self):
        """Set end marker at current position"""
        if self.video_player:
            current_pos = self.video_player.get_position()
            # Only set end marker if it's after start marker
            if self.start_marker is None or current_pos > self.start_marker:
                self.end_marker = current_pos
                self.end_time_label.setText(f"End: {self.format_timestamp(self.end_marker/1000.0)}")
                self.update_slider_style()

    def update_slider_style(self):
        """Update slider style to show selected range"""
        style = """
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 8px;
                background: #B1B1B1;
                margin: 2px 0;
            }
            
            QSlider::handle:horizontal {
                background: #4A90E2;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
        """
        
        if self.start_marker is not None:
            start_percent = (self.start_marker / self.video_player.get_duration()) * 100
            if self.end_marker is not None:
                end_percent = (self.end_marker / self.video_player.get_duration()) * 100
                # Highlight selected range
                style += f"""
                    QSlider::groove:horizontal {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #B1B1B1,
                            stop:{start_percent/100} #B1B1B1,
                            stop:{start_percent/100} #4A90E2,
                            stop:{end_percent/100} #4A90E2,
                            stop:{end_percent/100} #B1B1B1,
                            stop:1 #B1B1B1);
                    }}
                """
            else:
                # Show start marker only
                style += f"""
                    QSlider::groove:horizontal {{
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #B1B1B1,
                            stop:{start_percent/100} #B1B1B1,
                            stop:{start_percent/100} #4A90E2,
                            stop:1 #4A90E2);
                    }}
                """
        
        self.slider.setStyleSheet(style)

    def change_max_speed(self, value):
        """Change the maximum speed on the speedometer"""
        try:
            max_speed = int(value)
            self.hud_renderer.set_max_speed(max_speed)
            if self.video_player:
                self.video_player.update_frame()
        except ValueError:
            pass

    def load_music(self):
        """Load background music file"""
        music_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Music File",
            "",
            "Audio Files (*.mp3 *.wav *.m4a)"
        )
        
        if music_path:
            if self.video_player.load_music(music_path):
                self.music_path = music_path
                # Get just the filename for display
                music_name = os.path.basename(music_path)
                QMessageBox.information(self, "Music Loaded", 
                                      f"Music file loaded: {music_name}\n\n"
                                      "The music will be added during export.")
            else:
                QMessageBox.warning(self, "Music Load Failed", 
                                  "Failed to load music file.\n"
                                  "The music will still be used during export.")

    def update_volume_icon(self, value):
        """Update the volume icon based on the current volume"""
        if value == 0:
            self.volume_btn.setText("🔇")  # Muted
        elif value < 33:
            self.volume_btn.setText("🔈")  # Low volume
        elif value < 66:
            self.volume_btn.setText("🔉")  # Medium volume
        else:
            self.volume_btn.setText("🔊")  # High volume

    def toggle_mute(self):
        """Toggle audio mute state"""
        if not hasattr(self, 'last_volume'):
            self.last_volume = 50

        if self.volume_slider.value() == 0:
            self.volume_slider.setValue(self.last_volume)
        else:
            self.last_volume = self.volume_slider.value()
            self.volume_slider.setValue(0)

class HUDOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.hud_renderer = HUDRenderer()
        self.telemetry_data = None
        
    def set_telemetry_data(self, data):
        self.telemetry_data = data
        self.update()
        
    def paintEvent(self, event):
        if not self.telemetry_data:
            return
            
        painter = QPainter(self)
        # Draw HUD elements using painter
        # This needs to be implemented to draw HUD using Qt instead of OpenCV
        # For now, we'll keep using OpenCV for the export

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = DroneHUDApp()
    window.show()
    sys.exit(app.exec())
