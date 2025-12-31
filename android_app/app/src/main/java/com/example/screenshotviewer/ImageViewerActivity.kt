package com.example.screenshotviewer

import android.Manifest
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.github.chrisbanes.photoview.PhotoView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.viewpager2.widget.ViewPager2
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream

class ImageViewerActivity : AppCompatActivity() {

    private lateinit var imageViewPager: ViewPager2
    private lateinit var saveImageButton: Button
    private lateinit var deleteButton: Button
    private lateinit var prevButton: Button
    private lateinit var nextButton: Button
    private lateinit var bottomBar: LinearLayout

    private var images: List<FileItem> = emptyList()
    private var currentPosition: Int = 0
    private var baseUrl: String = ""
    private var isUIVisible: Boolean = true

    private val STORAGE_PERMISSION_CODE = 100

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // 隐藏ActionBar
        supportActionBar?.hide()

        setContentView(R.layout.activity_image_viewer)

        // Get data from intent
        val imagesJson = intent.getStringExtra("IMAGES_JSON") ?: ""
        currentPosition = intent.getIntExtra("POSITION", 0)
        baseUrl = intent.getStringExtra("BASE_URL") ?: ""

        // Parse images list
        if (imagesJson.isNotEmpty()) {
            val gson = Gson()
            val type = object : TypeToken<List<FileItem>>() {}.type
            images = gson.fromJson(imagesJson, type)
        }

        initViews()
        setupViewPager()
        setupListeners()
    }

    private fun initViews() {
        imageViewPager = findViewById(R.id.imageViewPager)
        saveImageButton = findViewById(R.id.saveImageButton)
        deleteButton = findViewById(R.id.deleteButton)
        prevButton = findViewById(R.id.prevButton)
        nextButton = findViewById(R.id.nextButton)
        bottomBar = findViewById(R.id.bottomBar)
    }

    private fun setupViewPager() {
        val adapter = ImagePagerAdapter(images, baseUrl) {
            // 点击图片时切换UI显示/隐藏
            toggleUI()
        }
        imageViewPager.adapter = adapter
        imageViewPager.setCurrentItem(currentPosition, false)

        // 禁用用户滑动，只允许通过按钮切换图片
        imageViewPager.isUserInputEnabled = false

        // 更新图片信息
        updateImageInfo()

        // 监听页面变化
        imageViewPager.registerOnPageChangeCallback(object : ViewPager2.OnPageChangeCallback() {
            override fun onPageSelected(position: Int) {
                super.onPageSelected(position)
                currentPosition = position
                updateImageInfo()
            }
        })
    }

    private fun setupListeners() {
        saveImageButton.setOnClickListener {
            if (checkStoragePermission()) {
                saveImageToLocal()
            } else {
                requestStoragePermission()
            }
        }

        deleteButton.setOnClickListener {
            val currentImage = getCurrentImage()
            if (currentImage != null) {
                deleteCurrentImage(currentImage)
            }
        }

        prevButton.setOnClickListener {
            if (currentPosition > 0) {
                imageViewPager.setCurrentItem(currentPosition - 1, true)
            }
        }

        nextButton.setOnClickListener {
            if (currentPosition < images.size - 1) {
                imageViewPager.setCurrentItem(currentPosition + 1, true)
            }
        }
    }

    private fun updateImageInfo() {
        // 更新按钮状态
        prevButton.isEnabled = currentPosition > 0
        nextButton.isEnabled = currentPosition < images.size - 1
        prevButton.alpha = if (currentPosition > 0) 1f else 0.3f
        nextButton.alpha = if (currentPosition < images.size - 1) 1f else 0.3f
    }

    fun toggleUI() {
        isUIVisible = !isUIVisible

        if (isUIVisible) {
            // 显示UI
            bottomBar.animate()
                .translationY(0f)
                .alpha(1f)
                .setDuration(300)
                .start()

            prevButton.animate()
                .alpha(1f)
                .setDuration(300)
                .start()

            nextButton.animate()
                .alpha(1f)
                .setDuration(300)
                .start()
        } else {
            // 隐藏UI
            bottomBar.animate()
                .translationY(bottomBar.height.toFloat())
                .alpha(0f)
                .setDuration(300)
                .start()

            prevButton.animate()
                .alpha(0f)
                .setDuration(300)
                .start()

            nextButton.animate()
                .alpha(0f)
                .setDuration(300)
                .start()
        }
    }

    private fun saveImageToLocal() {
        lifecycleScope.launch {
            try {
                val currentImage = getCurrentImage()
                if (currentImage == null) {
                    Toast.makeText(this@ImageViewerActivity, "无法获取当前图片", Toast.LENGTH_SHORT).show()
                    return@launch
                }

                saveImageButton.isEnabled = false
                saveImageButton.text = "保存中..."

                val success = downloadImageToLocal(currentImage)
                if (success) {
                    Toast.makeText(
                        this@ImageViewerActivity,
                        "已保存到 DCIM/Screenshots/${currentImage.name}",
                        Toast.LENGTH_SHORT
                    ).show()

                    // 保存成功后自动删除服务器上的图片
                    deleteImageAfterSave(currentImage)
                } else {
                    Toast.makeText(
                        this@ImageViewerActivity,
                        "保存失败",
                        Toast.LENGTH_SHORT
                    ).show()
                    saveImageButton.isEnabled = true
                    saveImageButton.text = "保存到本地"
                }
            } catch (e: Exception) {
                Toast.makeText(
                    this@ImageViewerActivity,
                    "保存失败: ${e.message}",
                    Toast.LENGTH_LONG
                ).show()
                saveImageButton.isEnabled = true
                saveImageButton.text = "保存到本地"
            }
        }
    }

    private fun getCurrentImage(): FileItem? {
        val position = imageViewPager.currentItem
        return if (position >= 0 && position < images.size) images[position] else null
    }

    private suspend fun downloadImageToLocal(image: FileItem): Boolean {
        return withContext(Dispatchers.IO) {
            try {
                val client = RetrofitClient.getOkHttpClient()
                val imageUrl = "$baseUrl/stream/${image.path}"
                val request = Request.Builder()
                    .url(imageUrl)
                    .build()

                val response = client.newCall(request).execute()
                if (!response.isSuccessful) return@withContext false

                val imageBytes = response.body?.bytes() ?: return@withContext false

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    // Android 10+: Use MediaStore API
                    val contentValues = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, image.name)
                        put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
                        put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_DCIM}/Screenshots")
                    }

                    val uri = contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, contentValues)
                    uri?.let {
                        contentResolver.openOutputStream(it)?.use { outputStream ->
                            outputStream.write(imageBytes)
                        }
                    } ?: return@withContext false
                } else {
                    // Android 9 and below: Use legacy file storage
                    val screenshotsDir = File(
                        Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DCIM),
                        "Screenshots"
                    )
                    if (!screenshotsDir.exists()) {
                        screenshotsDir.mkdirs()
                    }

                    val outputFile = File(screenshotsDir, image.name)
                    FileOutputStream(outputFile).use { output ->
                        output.write(imageBytes)
                    }

                    // Notify media scanner so the image appears in gallery
                    val intent = Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE)
                    intent.data = android.net.Uri.fromFile(outputFile)
                    sendBroadcast(intent)
                }

                true
            } catch (e: Exception) {
                e.printStackTrace()
                false
            }
        }
    }

    private fun checkStoragePermission(): Boolean {
        return when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU -> {
                // Android 13+: Check READ_MEDIA_IMAGES permission
                ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.READ_MEDIA_IMAGES
                ) == PackageManager.PERMISSION_GRANTED
            }
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> {
                // Android 10-12: No permission needed for MediaStore
                true
            }
            else -> {
                // Android 9 and below: Check WRITE_EXTERNAL_STORAGE
                ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE
                ) == PackageManager.PERMISSION_GRANTED
            }
        }
    }

    private fun requestStoragePermission() {
        when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU -> {
                // Android 13+: Request READ_MEDIA_IMAGES
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.READ_MEDIA_IMAGES),
                    STORAGE_PERMISSION_CODE
                )
            }
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.M -> {
                // Android 6-12: Request WRITE_EXTERNAL_STORAGE
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE),
                    STORAGE_PERMISSION_CODE
                )
            }
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == STORAGE_PERMISSION_CODE) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                Toast.makeText(this, "存储权限已授予", Toast.LENGTH_SHORT).show()
                saveImageToLocal()
            } else {
                Toast.makeText(this, "需要存储权限才能保存图片", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun deleteImageAfterSave(image: FileItem) {
        lifecycleScope.launch {
            try {
                saveImageButton.text = "删除中..."

                val apiService = RetrofitClient.getClient(baseUrl + "/")
                val response = apiService.deleteFile(image.path)

                if (response.isSuccessful && response.body()?.success == true) {
                    Toast.makeText(this@ImageViewerActivity, "服务器图片已删除", Toast.LENGTH_SHORT).show()

                    // Remove image from list and update adapter
                    val mutableImages = images.toMutableList()
                    val position = imageViewPager.currentItem
                    mutableImages.removeAt(position)
                    images = mutableImages

                    if (images.isEmpty()) {
                        // No more images, close the viewer
                        finish()
                    } else {
                        // Update the ViewPager
                        val adapter = ImagePagerAdapter(images, baseUrl) {
                            toggleUI()
                        }
                        imageViewPager.adapter = adapter
                        // Stay at same position or go to previous if we deleted the last one
                        val newPosition = if (position >= images.size) images.size - 1 else position
                        imageViewPager.setCurrentItem(newPosition, false)
                        updateImageInfo()
                    }
                } else {
                    Toast.makeText(
                        this@ImageViewerActivity,
                        "删除失败: ${response.body()?.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            } catch (e: Exception) {
                Toast.makeText(
                    this@ImageViewerActivity,
                    "删除失败: ${e.message}",
                    Toast.LENGTH_SHORT
                ).show()
            } finally {
                saveImageButton.isEnabled = true
                saveImageButton.text = "保存到本地"
            }
        }
    }

    private fun confirmDeleteCurrentImage() {
        val currentImage = getCurrentImage()
        if (currentImage == null) {
            Toast.makeText(this, "无法获取当前图片", Toast.LENGTH_SHORT).show()
            return
        }

        AlertDialog.Builder(this)
            .setTitle("确认删除")
            .setMessage("确定要删除 ${currentImage.name} 吗？")
            .setPositiveButton("删除") { _, _ -> deleteCurrentImage(currentImage) }
            .setNegativeButton("取消", null)
            .show()
    }

    private fun deleteCurrentImage(image: FileItem) {
        lifecycleScope.launch {
            try {
                deleteButton.isEnabled = false
                deleteButton.text = "删除中..."

                val apiService = RetrofitClient.getClient(baseUrl + "/")
                val response = apiService.deleteFile(image.path)

                if (response.isSuccessful && response.body()?.success == true) {
                    Toast.makeText(this@ImageViewerActivity, "删除成功", Toast.LENGTH_SHORT).show()

                    // Remove image from list and update adapter
                    val mutableImages = images.toMutableList()
                    val position = imageViewPager.currentItem
                    mutableImages.removeAt(position)
                    images = mutableImages

                    if (images.isEmpty()) {
                        // No more images, close the viewer
                        finish()
                    } else {
                        // Update the ViewPager
                        val adapter = ImagePagerAdapter(images, baseUrl) {
                            toggleUI()
                        }
                        imageViewPager.adapter = adapter
                        // Stay at same position or go to previous if we deleted the last one
                        val newPosition = if (position >= images.size) images.size - 1 else position
                        imageViewPager.setCurrentItem(newPosition, false)
                        updateImageInfo()
                    }
                } else {
                    Toast.makeText(
                        this@ImageViewerActivity,
                        "删除失败: ${response.body()?.message}",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            } catch (e: Exception) {
                Toast.makeText(
                    this@ImageViewerActivity,
                    "删除失败: ${e.message}",
                    Toast.LENGTH_LONG
                ).show()
            } finally {
                deleteButton.isEnabled = true
                deleteButton.text = "删除"
            }
        }
    }
}
