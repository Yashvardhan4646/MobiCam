package com.example.mycamserver

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.ImageFormat
import android.graphics.YuvImage
import android.graphics.Rect
import android.net.wifi.WifiManager
import android.os.Bundle
import android.os.PowerManager
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.net.NetworkInterface
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {

    private var server: MjpegStreamServer? = null
    private var cameraProvider: ProcessCameraProvider? = null
    private var cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA
    private var wakeLock: PowerManager.WakeLock? = null

    private val cameraExecutor = Executors.newSingleThreadExecutor()

    private var isStreamingState = mutableStateOf(false)
    private var ipAddressState = mutableStateOf("127.0.0.1")
    private var isDimmedState = mutableStateOf(false)

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            startCameraServer()
        } else {
            Toast.makeText(this, "Camera permission is required to stream video", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "MyCamServer::WakeLock")

        ipAddressState.value = getLocalIpAddress()

        setContent {
            MyCamServerTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = if (isDimmedState.value) Color.Black else Color(0xFF121212)
                ) {
                    if (isDimmedState.value) {
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(Color.Black),
                            contentAlignment = Alignment.Center
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("💡 Screen Dimmed (Saving Power)", color = Color.Gray, fontSize = 16.sp)
                                Spacer(modifier = Modifier.height(16.dp))
                                Button(
                                    onClick = { isDimmedState.value = false },
                                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF00ADB5))
                                ) {
                                    Text("Turn Screen On", color = Color.Black)
                                }
                            }
                        }
                    } else {
                        MainScreen(
                            isStreaming = isStreamingState.value,
                            ipAddress = ipAddressState.value,
                            onToggleStream = { toggleStream() },
                            onSwitchCamera = { switchCamera() },
                            onToggleDim = { isDimmedState.value = true }
                        )
                    }
                }
            }
        }
    }

    private fun toggleStream() {
        if (isStreamingState.value) {
            stopCameraServer()
        } else {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                startCameraServer()
            } else {
                requestPermissionLauncher.launch(Manifest.permission.CAMERA)
            }
        }
    }

    private fun startCameraServer() {
        try {
            if (server == null) {
                server = MjpegStreamServer(8080).apply { start() }
            }
            wakeLock?.acquire(10 * 60 * 1000L)
            bindCameraUseCases()
            isStreamingState.value = true
            Toast.makeText(this, "Stream started on port 8080", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            Toast.makeText(this, "Failed to start server: ${e.message}", Toast.LENGTH_LONG).show()
        }
    }

    private fun stopCameraServer() {
        try {
            server?.stop()
            server = null
            cameraProvider?.unbindAll()
            if (wakeLock?.isHeld == true) wakeLock?.release()
            isStreamingState.value = false
            Toast.makeText(this, "Stream stopped", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun switchCamera() {
        cameraSelector = if (cameraSelector == CameraSelector.DEFAULT_BACK_CAMERA) {
            CameraSelector.DEFAULT_FRONT_CAMERA
        } else {
            CameraSelector.DEFAULT_BACK_CAMERA
        }
        if (isStreamingState.value) {
            bindCameraUseCases()
        }
    }

    private fun bindCameraUseCases() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener({
            cameraProvider = cameraProviderFuture.get()
            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build()

            imageAnalysis.setAnalyzer(cameraExecutor) { imageProxy ->
                val jpegBytes = imageProxyToJpeg(imageProxy)
                imageProxy.close()
                if (jpegBytes != null) {
                    server?.updateFrame(jpegBytes)
                }
            }

            try {
                cameraProvider?.unbindAll()
                cameraProvider?.bindToLifecycle(this, cameraSelector, imageAnalysis)
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun imageProxyToJpeg(image: ImageProxy): ByteArray? {
        try {
            val width = image.width
            val height = image.height

            val yPlane = image.planes[0]
            val uPlane = image.planes[1]
            val vPlane = image.planes[2]

            val yBuffer = yPlane.buffer
            val uBuffer = uPlane.buffer
            val vBuffer = vPlane.buffer

            yBuffer.rewind()
            uBuffer.rewind()
            vBuffer.rewind()

            val ySize = yBuffer.remaining()
            val uSize = uBuffer.remaining()
            val vSize = vBuffer.remaining()

            val nv21 = ByteArray(width * height * 3 / 2)

            val yRowStride = yPlane.rowStride
            val yPixelStride = yPlane.pixelStride

            var pos = 0
            if (yRowStride == width && yPixelStride == 1) {
                val copyLen = Math.min(ySize, width * height)
                yBuffer.get(nv21, 0, copyLen)
                pos = width * height
            } else {
                for (row in 0 until height) {
                    yBuffer.position(row * yRowStride)
                    yBuffer.get(nv21, pos, width)
                    pos += width
                }
            }

            val uvRowStride = uPlane.rowStride
            val uvPixelStride = uPlane.pixelStride
            val uvWidth = width / 2
            val uvHeight = height / 2

            if (uvPixelStride == 2 && vPlane.buffer === uPlane.buffer) {
                val uvSize = Math.min(vBuffer.remaining(), width * height / 2)
                vBuffer.get(nv21, pos, uvSize)
            } else {
                for (row in 0 until uvHeight) {
                    val uRowPos = row * uvRowStride
                    val vRowPos = row * uvRowStride
                    for (col in 0 until uvWidth) {
                        val vIndex = vRowPos + col * uvPixelStride
                        val uIndex = uRowPos + col * uvPixelStride
                        if (vIndex < vSize) {
                            nv21[pos++] = vBuffer.get(vIndex)
                        }
                        if (uIndex < uSize) {
                            nv21[pos++] = uBuffer.get(uIndex)
                        }
                    }
                }
            }

            val yuvImage = YuvImage(nv21, ImageFormat.NV21, width, height, null)
            val out = ByteArrayOutputStream()
            yuvImage.compressToJpeg(Rect(0, 0, width, height), 75, out)
            return out.toByteArray()
        } catch (e: Exception) {
            e.printStackTrace()
            return null
        }
    }

    private fun getLocalIpAddress(): String {
        try {
            val interfaces = NetworkInterface.getNetworkInterfaces()
            val wifiIpList = mutableListOf<String>()
            val otherIpList = mutableListOf<String>()

            while (interfaces.hasMoreElements()) {
                val intf = interfaces.nextElement()
                if (!intf.isUp || intf.isLoopback) continue

                val addrs = intf.inetAddresses
                while (addrs.hasMoreElements()) {
                    val addr = addrs.nextElement()
                    if (!addr.isLoopbackAddress && addr is InetAddress) {
                        val host = addr.hostAddress ?: continue
                        if (host.indexOf(':') < 0 && host != "127.0.0.1") {
                            val name = intf.name.lowercase()
                            if (name.startsWith("wlan") || name.startsWith("ap") || name.startsWith("eth")) {
                                wifiIpList.add(host)
                            } else {
                                otherIpList.add(host)
                            }
                        }
                    }
                }
            }
            if (wifiIpList.isNotEmpty()) return wifiIpList.first()
            if (otherIpList.isNotEmpty()) return otherIpList.first()
        } catch (_: Exception) { }
        return "192.168.1.100"
    }

    override fun onDestroy() {
        super.onDestroy()
        stopCameraServer()
        cameraExecutor.shutdown()
    }
}

@Composable
fun MyCamServerTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Color(0xFF00ADB5),
            background = Color(0xFF121212),
            surface = Color(0xFF1E1E1E)
        ),
        content = content
    )
}

@Composable
fun MainScreen(
    isStreaming: Boolean,
    ipAddress: String,
    onToggleStream: () -> Unit,
    onSwitchCamera: () -> Unit,
    onToggleDim: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.SpaceBetween
    ) {
        // Title Header
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "📱 MyCam Server",
                fontSize = 24.sp,
                fontWeight = FontWeight.Bold,
                color = Color(0xFF00ADB5)
            )
            Text(
                text = if (isStreaming) "Status: LIVE 🟢" else "Status: Stopped 🔴",
                fontSize = 14.sp,
                color = if (isStreaming) Color(0xFF00E676) else Color(0xFFFF4D4D)
            )
        }

        // IP Connection Box
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = CardDefaults.cardColors(containerColor = Color(0xFF1E1E1E))
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("Connect Your PC Viewer To:", color = Color.LightGray, fontSize = 13.sp)
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "http://$ipAddress:8080/video",
                    fontSize = 16.sp,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    color = Color(0xFF00ADB5)
                )
            }
        }

        // Action Buttons
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Button(
                onClick = onToggleStream,
                modifier = Modifier.fillMaxWidth().height(52.dp),
                shape = RoundedCornerShape(10.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (isStreaming) Color(0xFFFF4D4D) else Color(0xFF00ADB5)
                )
            ) {
                Text(
                    text = if (isStreaming) "⏹ STOP STREAM" else "▶ START STREAM",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                    color = Color.White
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                OutlinedButton(
                    onClick = onSwitchCamera,
                    modifier = Modifier.weight(1f).height(46.dp),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text("🔄 Switch Cam", color = Color.White)
                }

                OutlinedButton(
                    onClick = onToggleDim,
                    modifier = Modifier.weight(1f).height(46.dp),
                    shape = RoundedCornerShape(10.dp)
                ) {
                    Text("💡 Dim Screen", color = Color.White)
                }
            }
        }
    }
}
