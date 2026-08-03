package com.example.mycamserver

import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit

class MjpegStreamServer(port: Int = 8080) : NanoHTTPD(port) {

    @Volatile
    private var latestFrame: ByteArray? = null
    private val listeners = CopyOnWriteArrayList<(ByteArray) -> Unit>()

    fun updateFrame(jpegBytes: ByteArray) {
        latestFrame = jpegBytes
        listeners.forEach { listener ->
            try {
                listener(jpegBytes)
            } catch (_: Exception) { }
        }
    }

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri
        return when {
            uri == "/video" || uri == "/mjpegfeed" || uri.startsWith("/video?") || uri.startsWith("/mjpegfeed?") -> {
                val boundary = "jpgboundary"
                val inputStream = MjpegInputStream(boundary)
                newChunkedResponse(
                    Response.Status.OK,
                    "multipart/x-mixed-replace; boundary=$boundary",
                    inputStream
                ).apply {
                    addHeader("Cache-Control", "no-store, no-cache, must-revalidate, pre-check=0, post-check=0, max-age=0")
                    addHeader("Pragma", "no-cache")
                    addHeader("Connection", "close")
                }
            }
            else -> {
                val hostHeader = session.headers["host"] ?: "IP:8080"
                val html = """
                    <!DOCTYPE html>
                    <html>
                    <head>
                        <title>MyCam Server</title>
                        <meta name="viewport" content="width=device-width, initial-scale=1">
                        <style>
                            body { font-family: sans-serif; background: #121212; color: #fff; text-align: center; margin: 0; padding: 20px; }
                            h2 { color: #00adb5; }
                            img { max-width: 100%; height: auto; border: 2px solid #00adb5; border-radius: 8px; }
                        </style>
                    </head>
                    <body>
                        <h2>📱 MyCam Server Live Stream</h2>
                        <p>Stream URL: <code>http://$hostHeader/video</code></p>
                        <br>
                        <img src="/video" alt="Live Camera Stream">
                    </body>
                    </html>
                """.trimIndent()
                newFixedLengthResponse(Response.Status.OK, "text/html", html)
            }
        }
    }

    private inner class MjpegInputStream(private val boundary: String) : InputStream() {
        private val frameQueue = ArrayBlockingQueue<ByteArray>(2)
        private var currentFrameStream: ByteArrayInputStream? = null
        @Volatile
        private var isClosed = false

        private val listener: (ByteArray) -> Unit = { jpeg ->
            if (!isClosed) {
                if (frameQueue.remainingCapacity() == 0) {
                    frameQueue.poll()
                }
                frameQueue.offer(jpeg)
            }
        }

        init {
            listeners.add(listener)
            latestFrame?.let {
                frameQueue.offer(it)
            }
        }

        private fun createFrameStream(jpeg: ByteArray): ByteArrayInputStream {
            val header = "--$boundary\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpeg.size}\r\n\r\n"
            val out = ByteArrayOutputStream(header.length + jpeg.size + 2)
            out.write(header.toByteArray(Charsets.US_ASCII))
            out.write(jpeg)
            out.write("\r\n".toByteArray(Charsets.US_ASCII))
            return ByteArrayInputStream(out.toByteArray())
        }

        private fun ensureFrameStream(): Boolean {
            if (isClosed) return false
            while (!isClosed && (currentFrameStream == null || currentFrameStream!!.available() == 0)) {
                try {
                    val nextJpeg = frameQueue.poll(100, TimeUnit.MILLISECONDS)
                    if (nextJpeg != null) {
                        currentFrameStream = createFrameStream(nextJpeg)
                        return true
                    }
                } catch (_: InterruptedException) {
                    isClosed = true
                    return false
                }
            }
            return !isClosed && currentFrameStream != null && currentFrameStream!!.available() > 0
        }

        override fun read(): Int {
            if (!ensureFrameStream()) return -1
            return currentFrameStream?.read() ?: -1
        }

        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (!ensureFrameStream()) return -1
            return currentFrameStream?.read(b, off, len) ?: -1
        }

        override fun close() {
            isClosed = true
            listeners.remove(listener)
            frameQueue.clear()
            super.close()
        }
    }
}
