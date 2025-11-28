from flask import Flask, render_template, request, redirect, url_for
import os
import config
import json
import subprocess
import signal

app = Flask(__name__)
UPLOAD_FOLDER = 'mp3'
MAPPING_FILE = 'mp3_mapping.json'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

mpg123_process = None

@app.route('/')
def index():
    mp3_files = os.listdir(UPLOAD_FOLDER)
    current_mapping = {}
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE) as f:
            current_mapping = json.load(f)
    return render_template('index.html', mp3_files=mp3_files, config=config, mapping=current_mapping)

@app.route('/upload', methods=['POST'])
def upload_file():
    file = request.files['file']
    if file and file.filename.endswith('.mp3'):
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))
    return redirect(url_for('index'))

@app.route('/set_alarm', methods=['POST'])
def set_alarm():
    hour = int(request.form['hour'])
    minute = int(request.form['minute'])

    with open('config.py', 'r') as f:
        lines = f.readlines()

    with open('config.py', 'w') as f:
        for line in lines:
            if line.startswith('ALARM_HOUR'):
                f.write(f'ALARM_HOUR = {hour}\n')
            elif line.startswith('ALARM_MINUTE'):
                f.write(f'ALARM_MINUTE = {minute}\n')
            else:
                f.write(line)

    return redirect(url_for('index'))

@app.route('/set_mapping', methods=['POST'])
def set_mapping():
    date_key = request.form['date']  # format: YYYY-MM-DD or MM-DD
    filename = request.form['filename']
    mapping = {}
    if os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE, 'r') as f:
            mapping = json.load(f)
    mapping[date_key] = filename
    with open(MAPPING_FILE, 'w') as f:
        json.dump(mapping, f, indent=2)
    return redirect(url_for('index'))

@app.route('/play_now', methods=['POST'])
def play_now():
    global mpg123_process
    filepath = os.path.join(UPLOAD_FOLDER, config.MP3_FILE.split('/')[-1])
    mpg123_process = subprocess.Popen(["mpg123", filepath])
    return redirect(url_for('index'))

@app.route('/play_file/<filename>', methods=['POST'])
def play_file(filename):
    global mpg123_process
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        mpg123_process = subprocess.Popen(["mpg123", filepath])
    return redirect(url_for('index'))

@app.route('/stop', methods=['POST'])
def stop():
    global mpg123_process
    if mpg123_process and mpg123_process.poll() is None:
        mpg123_process.terminate()
        mpg123_process = None
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)