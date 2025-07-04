from flask import Flask, render_template, request
from flask_socketio import SocketIO
import subprocess, os, pty, select

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
socketio = SocketIO(app)

# Home route with navigation
@app.route('/')
def home():
    return render_template('home.html')

# Docker containers list
@app.route('/containers')
def containers():
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True
    )
    container_names = result.stdout.strip().splitlines()
    return render_template('containers.html', containers=container_names)

# Kubernetes pods list (with namespaces)
@app.route('/pods')
def pods():
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "--all-namespaces", "-o",
             "jsonpath={range .items[*]}{.metadata.namespace}:{.metadata.name} {end}"],
            capture_output=True, text=True, check=True
        )
        pods_raw = result.stdout.strip().split()
    except subprocess.CalledProcessError:
        pods_raw = []

    pods = []
    for entry in pods_raw:
        ns, pod = entry.split(":", 1)
        pods.append({'namespace': ns, 'name': pod})

    return render_template('pods.html', pods=pods)

# Terminal for Docker container
@app.route('/terminal/docker/<container>')
def docker_terminal(container):
    return render_template('terminal.html', container=container, type='docker', namespace='')

# Terminal for Kubernetes pod
@app.route('/terminal/k8s/<namespace>/<pod>')
def k8s_terminal(namespace, pod):
    return render_template('terminal.html', container=pod, namespace=namespace, type='k8s')

@socketio.on('start_shell')
def start_shell(data):
    container = data.get('container')
    type_ = data.get('type')
    namespace = data.get('namespace')

    pid, fd = pty.fork()

    if pid == 0:
        if type_ == 'docker':
            os.execvp("docker", ["docker", "exec", "-it", container, "/bin/sh"])
        elif type_ == 'k8s':
            if namespace:
                os.execvp("kubectl", ["kubectl", "exec", "-n", namespace, "-it", container, "--", "/bin/sh"])
            else:
                os.execvp("kubectl", ["kubectl", "exec", "-it", container, "--", "/bin/sh"])
        else:
            os._exit(1)
    else:
        socketio.start_background_task(read_shell_output, fd)

        @socketio.on('input')
        def handle_input(data):
            os.write(fd, data['data'].encode())

def read_shell_output(fd):
    while True:
        socketio.sleep(0.01)
        if select.select([fd], [], [], 0)[0]:
            output = os.read(fd, 1024).decode(errors='ignore')
            socketio.emit('output', {'data': output})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
