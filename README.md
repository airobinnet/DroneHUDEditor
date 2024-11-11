# Drone HUD Editor

Transform your DJI drone footage with professional heads-up display (HUD) overlays using original flight telemetry data. Create cinematic drone videos with real-time speed, altitude, GPS coordinates, and dynamic mapping.

![Drone HUD Editor Screenshot](screenshots/demo.png)

## ✨ Key Features

### 🎥 Video Processing
- Smart preview generation for smooth playback
- Hardware-accelerated video processing
- Custom start/end markers for export
- Background music integration with YouTube support

### 🎮 HUD Elements
- Dynamic speedometer with adjustable scale
- 3D compass with cardinal directions
- Real-time GPS coordinates and altitude
- Interactive mini-map with flight path
- Camera settings display (ISO, shutter)
- Customizable crosshair
- Horizontal compass bar
- All elements individually toggleable

### 🎨 Themes & Customization
- 4 Professional themes:
  - Default Green
  - Military
  - Modern Blue
  - Night Vision
- Adjustable opacity
- High-contrast text with shadows

### 🎵 Audio Features
- Local audio file support (MP3, WAV, M4A)
- Direct YouTube audio import
- Volume control with crossfading
- Audio preview during editing

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- Git (for cloning)

### Installation

1. Clone and enter directory:
```bash
git clone https://github.com/airobinnet/DroneHUDEditor.git
cd DroneHUDEditor
```

2. Create virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

### Running the App

```bash
python main.py
```

## 📖 Basic Usage

1. **Load Content**
   - Click "Load Video" or drag & drop
   - SRT files are auto-detected
   - Add background music (optional)

2. **Customize HUD**
   - Toggle elements with checkboxes
   - Choose theme from dropdown
   - Adjust speedometer range
   - Real-time preview updates

3. **Export**
   - Set start/end markers (optional)
   - Click "Export"
   - Choose quality settings
   - Add background music
   - Monitor progress

## 🛠 Technical Details

- Built with PyQt6 and OpenCV
- Multi-threaded frame processing
- Efficient frame buffering
- OpenStreetMap integration
- Hardware acceleration support

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/Amazing`)
3. Commit changes (`git commit -m 'Add Amazing Feature'`)
4. Push to branch (`git push origin feature/Amazing`)
5. Open Pull Request

## 📄 License

MIT License - see [LICENSE](LICENSE) file

## 💡 Support

- Issues: Use GitHub issue tracker
- Questions: Open a discussion
- Updates: Watch repository for releases

---
Made with ❤️ by drone enthusiasts, for drone enthusiasts