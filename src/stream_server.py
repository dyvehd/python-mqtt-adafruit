import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import ThreadingMixIn

logger = logging.getLogger(__name__)


class ThreadedHTTPServer(ThreadingHTTPServer):
    """Allows multi-threaded concurrent request handling (e.g. multi-page dashboard views)."""
    daemon_threads = True


class MJPEGStreamServer:
    """Lightweight HTTP server that streams annotated frames from the active AI Provider.

    Serves frames over standard MJPEG (multipart/x-mixed-replace) natively supported by browsers.
    """

    def __init__(self, ai_provider, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.ai_provider = ai_provider
        self.host = host
        self.port = port
        self.server = None
        self._thread = None

    def start(self) -> None:
        provider = self.ai_provider

        class MJPEGStreamHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # Silence standard connection logging to keep console clean
                logger.debug(format % args)

            def do_GET(self):
                if self.path == "/video_feed":
                    self.send_response(200)
                    self.send_header("Age", "0")
                    self.send_header(
                        "Cache-Control",
                        "no-cache, private, no-store, must-revalidate, max-age=0, post-check=0, pre-check=0",
                    )
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                    logger.info("Client %s subscribed to live camera stream", self.client_address)

                    try:
                        while True:
                            jpeg_bytes = provider.get_latest_jpeg()
                            if jpeg_bytes is not None:
                                self.wfile.write(b"--frame\r\n")
                                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                                self.wfile.write(
                                    f"Content-Length: {len(jpeg_bytes)}\r\n\r\n".encode()
                                )
                                self.wfile.write(jpeg_bytes)
                                self.wfile.write(b"\r\n")
                            else:
                                # Stream is starting up, wait briefly
                                time.sleep(0.1)
                                continue

                            # Sleep slightly (~16ms) to align frame push with webcam FPS
                            time.sleep(0.06)
                    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                        logger.info("Client %s unsubscribed from stream", self.client_address)
                    except Exception as e:
                        logger.warning("Stream exception for client %s: %s", self.client_address, e)
                else:
                    self.send_response(404)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b"Not Found")

        self.server = ThreadedHTTPServer((self.host, self.port), MJPEGStreamHandler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("MJPEG Live Streaming Server started at http://%s:%d/video_feed", self.host, self.port)

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("MJPEG Live Streaming Server stopped")
