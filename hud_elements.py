import cv2
import numpy as np
from themes import Theme, Themes
import folium
import io
from PIL import Image
import requests
import math
import bisect

class HUDRenderer:
    def __init__(self):
        self.font = cv2.FONT_HERSHEY_SIMPLEX
        self.show_preview = True
        self.theme = Themes.DEFAULT.value
        
        # HUD Elements visibility flags
        self.show_iso = True
        self.show_shutter = True
        self.show_coords = True
        self.show_altitude = True
        self.show_crosshair = True
        self.show_compass = True
        self.show_speedometer = True
        self.show_horizontal_compass = True
        
        # Speedometer settings
        self.max_speed = 50  # Default max speed in km/h
        self.speed_step = 10  # Step size for speed markings

        # Add map settings
        self.show_map = True
        self.map_size_factor = 0.2  # 20% of video height
        self.map_size = 256  # Default size, will be updated based on video dimensions
        self.map_zoom = 17
        self.map_cache = {}
        self.path_points = []
        self.max_path_points = 100

        # Add pre-rendered map data
        self.pre_rendered_maps = {}
        self.telemetry_data = None

    def set_theme(self, theme: Theme):
        """Set the HUD theme"""
        self.theme = theme

    def set_max_speed(self, max_speed_kmh):
        """Set the maximum speed for the speedometer in km/h"""
        self.max_speed = max_speed_kmh
        # Adjust step size based on max speed
        self.speed_step = max(5, (max_speed_kmh // 5))  # At least 5 steps

    def render(self, frame, telemetry_data):
        if not self.show_preview:
            return frame

        height, width = frame.shape[:2]
        
        # Calculate map size based on video height
        self.map_size = int(height * self.map_size_factor)
        
        # Dynamic scaling based on resolution
        self.font_scale = min(width, height) / 1500.0  # Reduced scale for less overlap
        self.thickness = max(1, int(self.font_scale * 2))
        
        # Create overlay
        overlay = frame.copy()
        
        # Calculate layout zones
        margin = int(min(width, height) * 0.02)
        compass_size = int(min(width, height) * 0.15)  # Reduced size
        speedometer_size = int(min(width, height) * 0.15)  # Reduced size
        
        # Top section layout
        top_margin = margin
        bottom_margin = height - margin
        left_margin = margin
        right_margin = width - margin
        
        # Draw horizontal compass at the top
        if self.show_horizontal_compass:
            self.draw_horizontal_compass(overlay, telemetry_data['HEADING'], 
                                       top_margin + int(height * 0.02))
        
        # Draw main elements
        if self.show_compass:
            self.draw_compass(overlay, telemetry_data['HEADING'], 
                            (right_margin - compass_size//2, top_margin + compass_size//2),
                            compass_size)
            
        if self.show_speedometer:
            self.draw_speedometer(overlay, telemetry_data['SPEED']['TWOD'] * 3.6,
                                (left_margin + speedometer_size//2, top_margin + speedometer_size//2),
                                speedometer_size)
        
        if self.show_crosshair:
            self.draw_crosshair(overlay, (width//2, height//2))
        
        # Left side information (below speedometer)
        y_pos = top_margin + speedometer_size + margin + int(speedometer_size * 0.2)
        if self.show_iso:
            self.draw_text(overlay, f"ISO {telemetry_data['ISO']}", 
                          (left_margin, y_pos))
            y_pos += int(height * 0.04)
            
        if self.show_shutter:
            self.draw_text(overlay, f"1/{telemetry_data['SHUTTER']:.0f}", 
                          (left_margin, y_pos))
            y_pos += int(height * 0.04)
        
        # Right side information (below compass)
        if self.show_coords:
            y_pos = top_margin + compass_size + margin + int(compass_size * 0.2)
            lat = telemetry_data['GPS']['LATITUDE']
            lon = telemetry_data['GPS']['LONGITUDE']
            
            # Calculate text width for right alignment
            lat_text = f"LAT: {lat:.6f}"
            lon_text = f"LON: {lon:.6f}"
            
            self.draw_text(overlay, lat_text, 
                          (right_margin, y_pos), align_right=True)
            y_pos += int(height * 0.04)
            self.draw_text(overlay, lon_text, 
                          (right_margin, y_pos), align_right=True)
        
        # Bottom information with better spacing
        if self.show_altitude:
            bottom_y = bottom_margin - int(height * 0.04)
            
            # Left aligned altitude
            alt_text = f"ALT: {telemetry_data['ALTITUDE']:.1f}m"
            self.draw_text(overlay, alt_text, (left_margin, bottom_y))
            
            # Center aligned speed
            speed_text = f"SPEED: {telemetry_data['SPEED']['TWOD'] * 3.6:.1f} km/h"
            self.draw_text(overlay, speed_text, (width//2, bottom_y), center=True)
            
            # Right aligned vertical speed
            vspeed_text = f"V.SPEED: {telemetry_data['SPEED']['VERTICAL'] * 3.6:+.1f} km/h"
            self.draw_text(overlay, vspeed_text, (right_margin, bottom_y), align_right=True)

        # Add map if enabled
        if self.show_map:
            try:
                frame_num = telemetry_data.get('FRAMECNT', 0)
                
                # Find closest pre-rendered frame
                frame_nums = sorted(self.pre_rendered_maps.keys())
                closest_frame = min(frame_nums, key=lambda x: abs(x - frame_num))
                map_img = self.pre_rendered_maps[closest_frame]
                
                if map_img is not None:
                    # Calculate new map size based on current frame height
                    new_map_size = int(height * self.map_size_factor)
                    
                    # Ensure map_img is the correct size
                    if map_img.shape[0] != new_map_size or map_img.shape[1] != new_map_size:
                        map_img = cv2.resize(map_img, (new_map_size, new_map_size))
                    
                    compass_size = int(min(width, height) * 0.15)
                    map_x = width - new_map_size - 20
                    map_y = top_margin + compass_size + margin + int(height * 0.15)
                    
                    # Ensure we have enough space in the overlay
                    if (map_y + new_map_size <= height and 
                        map_x + new_map_size <= width):
                        
                        # Create semi-transparent background
                        cv2.rectangle(overlay, 
                                    (map_x-5, map_y-5),
                                    (map_x + new_map_size+5, map_y + new_map_size+5),
                                    (0, 0, 0), -1)
                        
                        # Create a properly sized slice of the overlay
                        overlay[map_y:map_y+new_map_size, 
                               map_x:map_x+new_map_size] = map_img
                
            except Exception as e:
                print(f"Error rendering map: {e}")
                import traceback
                traceback.print_exc()  # Print full error trace for debugging
        
        # Blend overlay with original frame
        cv2.addWeighted(overlay, self.theme.opacity/255, frame, 
                       1 - self.theme.opacity/255, 0, frame)
        
        return frame

    def draw_text(self, frame, text, pos, align_right=False, center=False):
        """Helper method to draw text with consistent styling"""
        (text_width, text_height), baseline = cv2.getTextSize(
            text, self.font, self.font_scale, self.thickness)
        
        x, y = pos
        if align_right:
            x -= text_width
        elif center:
            x -= text_width // 2
            
        # Draw text shadow for better visibility
        cv2.putText(frame, text, 
                    (x + 2, y + 2),
                    self.font, self.font_scale,
                    (0, 0, 0), self.thickness + 1)
                    
        # Draw main text
        cv2.putText(frame, text,
                    (x, y),
                    self.font, self.font_scale,
                    self.theme.primary_color, self.thickness)

    def draw_compass(self, frame, heading, center, size):
        """Draw compass overlay with heading indicator"""
        x, y = center
        radius = size // 2
        
        # Draw compass background
        cv2.circle(frame, (x, y), radius, (0, 0, 0), -1)
        cv2.circle(frame, (x, y), radius - 2, self.theme.secondary_color, 2)
        
        # Adjust heading by 180 degrees to correct orientation
        adjusted_heading = (heading + 180) % 360
        
        # Draw cardinal directions
        directions = ['N', 'E', 'S', 'W']
        angles = [0, 90, 180, 270]
        
        for direction, angle in zip(directions, angles):
            # Adjust angle based on heading
            angle_rad = np.deg2rad(angle - adjusted_heading + 90)
            text_radius = radius - int(radius * 0.3)
            text_x = int(x + text_radius * np.cos(angle_rad))
            text_y = int(y + text_radius * np.sin(angle_rad))
            
            # Use red for North, white for others
            color = (0, 0, 255) if direction == 'N' else self.theme.secondary_color
            
            self.draw_text(frame, direction, (text_x, text_y), center=True)
        
        # Draw heading needle
        needle_length = radius - int(radius * 0.2)
        angle_rad = np.deg2rad(-adjusted_heading + 90)
        end_x = int(x + needle_length * np.cos(angle_rad))
        end_y = int(y + needle_length * np.sin(angle_rad))
        
        cv2.line(frame, (x, y), (end_x, end_y), (0, 0, 255), 2)
        
        # Display heading value
        # heading_text = f"{int(heading)}"
        # self.draw_text(frame, heading_text, (x, y + radius + 20), center=True)

    def draw_speedometer(self, frame, speed_kmh, center, size):
        """Draw speedometer overlay"""
        x, y = center
        radius = size // 2
        
        # Draw speedometer background
        cv2.circle(frame, (x, y), radius, (0, 0, 0), -1)
        cv2.circle(frame, (x, y), radius - 2, self.theme.secondary_color, 2)
        
        # Draw speed markings
        max_speed = self.max_speed  # Use configurable max speed
        step = self.speed_step  # Use configurable step size
        
        for i in range(0, max_speed + step, step):  # Draw marks at each step
            angle = 180 - (i / max_speed * 180)
            angle_rad = np.deg2rad(angle)
            
            start_radius = radius - int(radius * 0.15)
            end_radius = radius - int(radius * 0.25)
            
            start_x = int(x + start_radius * np.cos(angle_rad))
            start_y = int(y + start_radius * np.sin(angle_rad))
            end_x = int(x + end_radius * np.cos(angle_rad))
            end_y = int(y + end_radius * np.sin(angle_rad))
            
            cv2.line(frame, (start_x, start_y), (end_x, end_y), 
                    self.theme.secondary_color, 2)
            
            if i % (step * 2) == 0:  # Draw numbers at every other step
                text_radius = radius - int(radius * 0.35)
                text_x = int(x + text_radius * np.cos(angle_rad))
                text_y = int(y + text_radius * np.sin(angle_rad))
                self.draw_text(frame, str(i), (text_x, text_y), center=True)
        
        # Draw speed needle
        angle = 180 - (min(speed_kmh, max_speed) / max_speed * 180)
        angle_rad = np.deg2rad(angle)
        needle_length = radius - int(radius * 0.2)
        end_x = int(x + needle_length * np.cos(angle_rad))
        end_y = int(y + needle_length * np.sin(angle_rad))
        
        cv2.line(frame, (x, y), (end_x, end_y), self.theme.primary_color, 2)
        
        # Display speed value in the lower part of the speedometer
        speed_text = f"{speed_kmh:.1f} km/h"
        self.draw_text(frame, speed_text, 
                      (x, y + radius + int(radius * 0.2)), center=True)

    def draw_crosshair(self, frame, center):
        """Draw center crosshair overlay"""
        x, y = center
        size = int(min(frame.shape[:2]) * 0.03)  # Reduced size
        gap = size // 4
        
        # Draw crosshair lines
        cv2.line(frame, (x - size, y), (x - gap, y), self.theme.primary_color, 2)
        cv2.line(frame, (x + gap, y), (x + size, y), self.theme.primary_color, 2)
        cv2.line(frame, (x, y - size), (x, y - gap), self.theme.primary_color, 2)
        cv2.line(frame, (x, y + gap), (x, y + size), self.theme.primary_color, 2)
        
        # Draw center dot
        cv2.circle(frame, (x, y), 2, self.theme.primary_color, -1) 

    def preprocess_telemetry(self, telemetry_data, progress_callback=None):
        """Pre-process telemetry data to prepare map tiles and paths"""
        self.telemetry_data = telemetry_data
        self.path_points = []
        self.pre_rendered_maps = {}
        
        try:
            # Get first frame to calculate map size
            if len(telemetry_data) > 0:
                # Assuming we have video dimensions in telemetry or using default
                self.map_size = 256  # Use fixed size for pre-rendering
            
            # Extract all GPS coordinates
            for frame_num, data in enumerate(telemetry_data):
                if 'GPS' in data and 'LATITUDE' in data['GPS'] and 'LONGITUDE' in data['GPS']:
                    lat = float(data['GPS']['LATITUDE'])
                    lon = float(data['GPS']['LONGITUDE'])
                    self.path_points.append((lat, lon, frame_num))
            
            # Pre-render maps for key frames
            total_frames = len(telemetry_data)
            step = max(1, total_frames // 500)  # Pre-render 500 frames
            
            print("Pre-rendering map tiles...")
            last_map = None
            
            for i in range(0, total_frames, step):
                if progress_callback:
                    percent_complete = (i / total_frames) * 100
                    if not progress_callback(percent_complete):
                        print("Map pre-rendering canceled")
                        return
                
                data = telemetry_data[i]
                lat = float(data['GPS']['LATITUDE'])
                lon = float(data['GPS']['LONGITUDE'])
                
                # Get map for this position
                map_img = self.get_map_tile(lat, lon, self.map_zoom, i)
                if map_img is not None:
                    self.pre_rendered_maps[i] = map_img
                    last_map = map_img
                elif last_map is not None:
                    self.pre_rendered_maps[i] = last_map
            
            if progress_callback:
                progress_callback(100)
                
            print("Map pre-rendering complete")
            
        except Exception as e:
            print(f"Error pre-processing telemetry: {e}")

    def get_map_tile(self, lat, lon, zoom=17, frame_num=None):
        """Get a map tile with path up to current frame"""
        cache_key = f"{lat:.6f},{lon:.6f},{zoom},{frame_num}"
        
        if cache_key in self.map_cache:
            return self.map_cache[cache_key]
            
        try:
            # Convert lat/lon to tile coordinates
            n = 2.0 ** zoom
            lat_rad = math.radians(lat)
            
            # Get tile coordinates
            xtile = int((lon + 180.0) / 360.0 * n)
            ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
            
            # Create a 3x3 grid of tiles
            large_img = np.zeros((256 * 3, 256 * 3, 3), dtype=np.uint8)
            
            # Load 3x3 grid of tiles
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    try:
                        url = f"https://tile.openstreetmap.org/{zoom}/{xtile+dx}/{ytile+dy}.png"
                        headers = {'User-Agent': 'DroneHUD/1.0'}
                        
                        # Use cached tile if available
                        tile_cache_key = f"{zoom},{xtile+dx},{ytile+dy}"
                        if tile_cache_key in self.map_cache:
                            tile = self.map_cache[tile_cache_key]
                        else:
                            response = requests.get(url, headers=headers)
                            if response.status_code == 200:
                                img_array = np.frombuffer(response.content, np.uint8)
                                tile = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                                self.map_cache[tile_cache_key] = tile
                        
                        if tile is not None:
                            y_offset = (dy + 1) * 256
                            x_offset = (dx + 1) * 256
                            large_img[y_offset:y_offset+256, x_offset:x_offset+256] = tile
                            
                    except Exception as e:
                        continue
            
            def latlon_to_pixels(lat, lon):
                lat_rad = math.radians(lat)
                x_precise = (lon + 180.0) / 360.0 * n
                y_precise = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
                
                x_rel = x_precise - (xtile - 1)
                y_rel = y_precise - (ytile - 1)
                
                x_pixel = int(x_rel * 256)
                y_pixel = int(y_rel * 256)
                return (x_pixel, y_pixel)
            
            # Draw path up to current frame
            if frame_num is not None and self.path_points:
                path_points = []
                for p_lat, p_lon, f_num in self.path_points:
                    if f_num <= frame_num:
                        px, py = latlon_to_pixels(p_lat, p_lon)
                        if 0 <= px < 768 and 0 <= py < 768:
                            path_points.append((px, py))
                
                if len(path_points) > 1:
                    # Draw path
                    for i in range(len(path_points) - 1):
                        cv2.line(large_img, path_points[i], path_points[i + 1], 
                                (0, 0, 0), 4)
                        cv2.line(large_img, path_points[i], path_points[i + 1], 
                                (0, 0, 255), 2)
            
            # Draw current position
            px, py = latlon_to_pixels(lat, lon)
            if 0 <= px < 768 and 0 <= py < 768:
                cv2.circle(large_img, (px, py), 8, (0, 0, 0), 4)
                cv2.circle(large_img, (px, py), 8, (0, 0, 255), 2)
                cv2.circle(large_img, (px, py), 3, (0, 0, 255), -1)
            
            # Crop and resize
            center_x = px
            center_y = py
            crop_size = min(self.map_size * 2, 768)
            half_size = crop_size // 2
            
            crop_x1 = max(0, center_x - half_size)
            crop_y1 = max(0, center_y - half_size)
            crop_x2 = min(768, crop_x1 + crop_size)
            crop_y2 = min(768, crop_y1 + crop_size)
            
            if crop_x1 < 0: crop_x1, crop_x2 = 0, crop_size
            if crop_y1 < 0: crop_y1, crop_y2 = 0, crop_size
            if crop_x2 > 768: crop_x1, crop_x2 = 768 - crop_size, 768
            if crop_y2 > 768: crop_y1, crop_y2 = 768 - crop_size, 768
            
            cropped = large_img[crop_y1:crop_y2, crop_x1:crop_x2]
            final_img = cv2.resize(cropped, (self.map_size, self.map_size))
            
            # Cache the result
            self.map_cache[cache_key] = final_img
            return final_img
            
        except Exception as e:
            print(f"Error getting map tile: {e}")
            return None

    def render_static_elements(self, frame):
        """Render HUD elements that don't change during video"""
        if not self.show_preview:
            return None

        height, width = frame.shape[:2]
        overlay = np.zeros_like(frame)
        
        if self.show_crosshair:
            self.draw_crosshair(overlay, (width//2, height//2))
        
        # Add other static elements here
        
        return overlay

    def render_dynamic_elements(self, frame, telemetry_data):
        """Render HUD elements that change with telemetry data"""
        if not self.show_preview:
            return frame

        height, width = frame.shape[:2]
        overlay = frame.copy()
        
        # Draw all dynamic elements (compass, speedometer, text, map)
        # ... (rest of the render code, excluding static elements)
        
        return frame

    def draw_horizontal_compass(self, frame, heading, y_position):
        """Draw a horizontal compass bar at the top of the screen"""
        height, width = frame.shape[:2]
        
        # Compass bar dimensions
        bar_width = int(width * 0.5)  # 50% of screen width
        bar_height = int(height * 0.03)  # 3% of screen height
        bar_x = (width - bar_width) // 2
        
        # Draw background
        cv2.rectangle(frame, 
                     (bar_x - 2, y_position - 2),
                     (bar_x + bar_width + 2, y_position + bar_height + 2),
                     (0, 0, 0), -1)
        
        # Draw border
        cv2.rectangle(frame,
                     (bar_x, y_position),
                     (bar_x + bar_width, y_position + bar_height),
                     self.theme.secondary_color, 1)
        
        # Calculate visible range (120 degrees total, 60 degrees each side)
        degrees_visible = 120
        pixels_per_degree = bar_width / degrees_visible
        
        # Draw degree markers and labels
        for deg in range(-180, 181, 10):  # Full 360 degrees for smooth scrolling
            # Calculate position relative to current heading
            relative_deg = (deg - heading) % 360
            if relative_deg > 180:
                relative_deg -= 360
                
            # Check if degree mark is visible
            if -60 <= relative_deg <= 60:
                x_pos = bar_x + int((relative_deg + 60) * pixels_per_degree)
                
                # Draw marker line
                line_height = bar_height // 2 if deg % 30 == 0 else bar_height // 4
                cv2.line(frame,
                        (x_pos, y_position + bar_height),
                        (x_pos, y_position + bar_height - line_height),
                        self.theme.secondary_color, 1)
                
                # Draw cardinal directions and degree numbers
                if deg % 30 == 0:
                    if deg == 0:
                        label = "N"
                        color = (0, 0, 255)  # Red for North
                    elif deg == 90:
                        label = "E"
                        color = self.theme.secondary_color
                    elif deg == 180 or deg == -180:
                        label = "S"
                        color = self.theme.secondary_color
                    elif deg == -90:
                        label = "W"
                        color = self.theme.secondary_color
                    else:
                        label = str(abs(deg))
                        color = self.theme.secondary_color
                    
                    # Draw text above the bar
                    text_size = cv2.getTextSize(label, self.font, 
                                              self.font_scale * 0.8, self.thickness)[0]
                    text_x = x_pos - text_size[0] // 2
                    text_y = y_position - 5
                    
                    # Draw text shadow
                    cv2.putText(frame, label,
                               (text_x + 1, text_y + 1),
                               self.font, self.font_scale * 0.8,
                               (0, 0, 0), self.thickness + 1)
                    cv2.putText(frame, label,
                               (text_x, text_y),
                               self.font, self.font_scale * 0.8,
                               color, self.thickness)
        
        # Draw center indicator
        center_x = bar_x + bar_width // 2
        cv2.line(frame,
                 (center_x, y_position - 5),
                 (center_x, y_position + bar_height + 5),
                 (0, 255, 255), 2)  # Yellow center line