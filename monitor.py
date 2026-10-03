import sys
import socket
import ssl
import re

# CNT 4713 - Project 1
# Web Status Monitor

# get urls_file name from command line
if len(sys.argv) != 2:
    print('Usage: monitor urls_file')
    sys.exit()

# text file to get list of urls
urls_file = sys.argv[1]


def parse_url(url):
    """Return protocol, host, port, and path from a URL."""
    url = url.strip()

    if url.startswith('https://'):
        protocol = 'https'
        port = 443
        rest = url[8:]
    elif url.startswith('http://'):
        protocol = 'http'
        port = 80
        rest = url[7:]
    else:
        # The project input uses http:// or https:// URLs.
        protocol = 'http'
        port = 80
        rest = url

    slash = rest.find('/')
    if slash == -1:
        host_part = rest
        path = '/'
    else:
        host_part = rest[:slash]
        path = rest[slash:]
        if path == '':
            path = '/'

    # Allow an explicit port in a URL, if one is provided.
    if ':' in host_part:
        host, port_text = host_part.rsplit(':', 1)
        try:
            port = int(port_text)
        except ValueError:
            host = host_part
    else:
        host = host_part

    return protocol, host, port, path


def make_absolute_url(base_url, new_url):
    """Convert a redirect or referenced object URL to a complete URL."""
    new_url = new_url.strip()

    if new_url.startswith('http://') or new_url.startswith('https://'):
        return new_url

    protocol, host, port, path = parse_url(base_url)

    default_port = (protocol == 'http' and port == 80) or \
                   (protocol == 'https' and port == 443)

    if default_port:
        server = host
    else:
        server = host + ':' + str(port)

    if new_url.startswith('//'):
        return protocol + ':' + new_url

    if new_url.startswith('/'):
        return protocol + '://' + server + new_url

    # Relative path: place it in the same directory as the current page.
    if '/' in path:
        directory = path.rsplit('/', 1)[0] + '/'
    else:
        directory = '/'

    return protocol + '://' + server + directory + new_url


def receive_all(sock):
    """Receive the complete response until the server closes the connection."""
    response = b''

    while True:
        data = sock.recv(4096)
        if not data:
            break
        response += data

    return response


def fetch_url(url):
    """
    Fetch one URL using a socket.
    Returns (status_line, headers, body), or None for a network error.
    """
    protocol, host, port, path = parse_url(url)
    sock = None

    try:
        # create client socket, connect to server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))

        # HTTPS extra credit: protect the connected TCP socket with TLS.
        if protocol == 'https':
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)

        # send HTTP request
        request = f'GET {path} HTTP/1.0\r\n'
        request += f'Host: {host}\r\n'
        request += 'Connection: close\r\n'
        request += '\r\n'
        sock.sendall(bytes(request, 'utf-8'))

        # receive HTTP response
        response = receive_all(sock)

        if not response:
            return None

        # Split headers and body.
        header_end = response.find(b'\r\n\r\n')
        if header_end == -1:
            return None

        header_bytes = response[:header_end]
        body = response[header_end + 4:]

        header_text = header_bytes.decode('iso-8859-1')
        header_lines = header_text.split('\r\n')

        if len(header_lines) == 0:
            return None

        status_line = header_lines[0]

        # Store response headers using lowercase names.
        headers = {}
        for line in header_lines[1:]:
            if ':' in line:
                name, value = line.split(':', 1)
                headers[name.strip().lower()] = value.strip()

        return status_line, headers, body

    except Exception:
        return None

    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass


def status_text(status_line):
    """Remove HTTP version and return code/reason, such as 200 OK."""
    parts = status_line.split(' ', 1)
    if len(parts) == 2:
        return parts[1]
    return status_line


def status_code(status_line):
    """Return the numeric HTTP status code, or 0 if it cannot be parsed."""
    parts = status_line.split()
    if len(parts) >= 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def find_images(body):
    """Find src values from HTML img tags."""
    try:
        html = body.decode('utf-8', errors='ignore')
    except Exception:
        return []

    # Handles quoted and unquoted src values.
    pattern = r'<img\b[^>]*\bsrc\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|([^\s>]+))'
    matches = re.findall(pattern, html, flags=re.IGNORECASE)

    images = []
    for match in matches:
        image_url = match[0] or match[1] or match[2]
        if image_url and image_url not in images:
            images.append(image_url)

    return images


def print_referenced_objects(page_url, body):
    """Fetch and report images referenced by an HTML page."""
    images = find_images(body)

    for image in images:
        # Ignore data URLs because they are embedded in the HTML itself.
        if image.startswith('data:'):
            continue

        image_url = make_absolute_url(page_url, image)
        print('Referenced URL: ' + image_url)

        result = fetch_url(image_url)
        if result is None:
            print('Status: Network Error')
        else:
            image_status, image_headers, image_body = result
            print('Status: ' + status_text(image_status))


def monitor_url(url):
    """Fetch a URL, report its status, and handle redirects/referenced images."""
    print('URL: ' + url)

    result = fetch_url(url)
    if result is None:
        print('Status: Network Error')
        return

    current_status, headers, body = result
    print('Status: ' + status_text(current_status))

    code = status_code(current_status)

    # Follow the 301/302 redirect required by the project.
    if code == 301 or code == 302:
        if 'location' in headers:
            redirected_url = make_absolute_url(url, headers['location'])
            print('Redirected URL: ' + redirected_url)

            redirected_result = fetch_url(redirected_url)
            if redirected_result is None:
                print('Status: Network Error')
                return

            redirected_status, redirected_headers, redirected_body = redirected_result
            print('Status: ' + status_text(redirected_status))

            # If the redirected response is HTML, check its referenced images too.
            content_type = redirected_headers.get('content-type', '')
            if status_code(redirected_status) >= 200 and \
               status_code(redirected_status) < 300 and \
               'text/html' in content_type.lower():
                print_referenced_objects(redirected_url, redirected_body)

        return

    # For successful HTML pages, fetch referenced image objects.
    content_type = headers.get('content-type', '')
    if code >= 200 and code < 300 and 'text/html' in content_type.lower():
        print_referenced_objects(url, body)


# Read and monitor each URL once.
try:
    with open(urls_file, 'r') as file:
        urls = file.readlines()
except Exception:
    print('Network Error')
    sys.exit()

for url in urls:
    url = url.strip()
    if url:
        monitor_url(url)
