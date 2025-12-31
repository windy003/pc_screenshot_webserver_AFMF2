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

        // 设置缩放范围：最小0.5倍，中等1倍，最大10倍
        holder.photoView.minimumScale = 0.5f
        holder.photoView.mediumScale = 2f
        holder.photoView.maximumScale = 10f

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
                            holder.photoView.setImageBitmap(bitmap)
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
