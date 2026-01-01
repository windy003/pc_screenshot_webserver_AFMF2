package com.example.screenshotviewer

import android.graphics.BitmapFactory
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.recyclerview.widget.RecyclerView
import com.github.chrisbanes.photoview.PhotoView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Request

class ImagePagerAdapter(
    private val images: List<FileItem>,
    private val baseUrl: String,
    private val onImageClick: (() -> Unit)? = null
) : RecyclerView.Adapter<ImagePagerAdapter.ImageViewHolder>() {

    class ImageViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val photoView: PhotoView = view.findViewById(R.id.photoView)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ImageViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_image_pager, parent, false)
        return ImageViewHolder(view)
    }

    override fun onBindViewHolder(holder: ImageViewHolder, position: Int) {
        val item = images[position]
        val imageUrl = "$baseUrl/stream/${item.path}"

        // 设置点击监听器
        holder.photoView.setOnClickListener {
            onImageClick?.invoke()
        }

        // 显示 placeholder
        holder.photoView.setImageResource(android.R.drawable.ic_menu_gallery)

        // 加载图片
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val client = RetrofitClient.getOkHttpClient()
                val request = Request.Builder().url(imageUrl).build()
                val response = client.newCall(request).execute()

                if (response.isSuccessful) {
                    val inputStream = response.body?.byteStream()
                    val bitmap = BitmapFactory.decodeStream(inputStream)

                    withContext(Dispatchers.Main) {
                        if (bitmap != null) {
                            // 设置图片
                            holder.photoView.setImageBitmap(bitmap)

                            // 使用ViewTreeObserver等待PhotoView完成布局
                            holder.photoView.viewTreeObserver.addOnGlobalLayoutListener(object : android.view.ViewTreeObserver.OnGlobalLayoutListener {
                                override fun onGlobalLayout() {
                                    holder.photoView.viewTreeObserver.removeOnGlobalLayoutListener(this)

                                    // 等待PhotoView完成初始化后再调整缩放
                                    holder.photoView.post {
                                        try {
                                            // 获取PhotoView当前的显示宽度（PhotoView自己计算的）
                                            val currentDisplayRect = holder.photoView.displayRect
                                            val currentDisplayWidth = currentDisplayRect?.width() ?: 0f

                                            // 获取PhotoView容器的实际宽度
                                            val viewWidth = holder.photoView.width.toFloat()

                                            android.util.Log.d("ImagePagerAdapter", "ViewWidth: $viewWidth, Current DisplayRect width: $currentDisplayWidth")

                                            if (currentDisplayWidth > 0 && viewWidth > 0) {
                                                // 计算需要的缩放倍数（相对于当前显示）
                                                val scaleFactor = viewWidth / currentDisplayWidth
                                                val currentScale = holder.photoView.scale
                                                val targetScale = currentScale * scaleFactor

                                                android.util.Log.d("ImagePagerAdapter", "Scale factor: $scaleFactor")
                                                android.util.Log.d("ImagePagerAdapter", "Current scale: $currentScale, Target scale: $targetScale")

                                                // 限制targetScale在合理范围内 (0.1 到 50.0) - 放宽上限以支持大屏
                                                val safeTargetScale = targetScale.coerceIn(0.1f, 50.0f)

                                                if (safeTargetScale != targetScale) {
                                                    android.util.Log.w("ImagePagerAdapter", "Target scale $targetScale out of range, clamped to $safeTargetScale")
                                                }

                                                // 设置缩放范围 - 确保min < target < max
                                                val minScale = (safeTargetScale * 0.5f).coerceAtLeast(0.1f)
                                                val maxScale = (safeTargetScale * 5f).coerceAtMost(50.0f)
                                                val medScale = (safeTargetScale * 2f).coerceIn(minScale, maxScale)

                                                android.util.Log.d("ImagePagerAdapter", "Scale range: min=$minScale, target=$safeTargetScale, med=$medScale, max=$maxScale")

                                                // 按正确的顺序设置scale: 先max, 再medium, 最后min
                                                holder.photoView.maximumScale = maxScale
                                                holder.photoView.mediumScale = medScale
                                                holder.photoView.minimumScale = minScale

                                                // 应用缩放,并设置焦点为顶部中心,使图片顶部对齐屏幕顶部
                                                // setScale(scale, focalX, focalY, animate)
                                                // focalX = viewWidth/2 (水平居中), focalY = 0 (顶部对齐)
                                                holder.photoView.setScale(safeTargetScale, viewWidth / 2f, 0f, false)

                                                // 验证结果
                                                holder.photoView.postDelayed({
                                                    val finalDisplayRect = holder.photoView.displayRect
                                                    android.util.Log.d("ImagePagerAdapter", "Final - scale: ${holder.photoView.scale}")
                                                    android.util.Log.d("ImagePagerAdapter", "Final - DisplayRect width: ${finalDisplayRect?.width()}")
                                                }, 100)
                                            } else {
                                                android.util.Log.w("ImagePagerAdapter", "Invalid dimensions: viewWidth=$viewWidth, currentDisplayWidth=$currentDisplayWidth")
                                            }
                                        } catch (e: Exception) {
                                            android.util.Log.e("ImagePagerAdapter", "Error setting scale", e)
                                            e.printStackTrace()
                                        }
                                    }
                                }
                            })
                        } else {
                            holder.photoView.setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
                        }
                    }
                } else {
                    withContext(Dispatchers.Main) {
                        holder.photoView.setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                withContext(Dispatchers.Main) {
                    holder.photoView.setImageResource(android.R.drawable.ic_menu_close_clear_cancel)
                }
            }
        }
    }

    override fun getItemCount() = images.size
}
