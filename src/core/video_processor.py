import asyncio
import subprocess
import shutil
import os
from pathlib import Path
from typing import List, Optional, Callable
import ffmpeg
import tempfile
import json


class FFmpegProcessor:
    def __init__(self, ffmpeg_path: Optional[str] = None):
        """
        FFmpeg视频处理器

        Args:
            ffmpeg_path: FFmpeg可执行文件路径，如果为None则从环境变量查找
        """
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        if not self.ffmpeg_path:
            raise Exception("未找到FFmpeg，请确保已安装并添加到PATH环境变量")

    def _find_ffmpeg(self) -> Optional[str]:
        """查找FFmpeg可执行文件"""
        # 常见的FFmpeg安装位置
        possible_paths = [
            'ffmpeg',
            'ffmpeg.exe',
            r'C:\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            '/usr/bin/ffmpeg',
            '/usr/local/bin/ffmpeg'
        ]

        for path in possible_paths:
            if shutil.which(path):
                return path
        return None

    async def merge_ts_segments(self,
                               segments_dir: Path,
                               output_file: Path,
                               progress_callback: Optional[Callable[[float], None]] = None) -> bool:
        """
        合并TS视频片段为MP4文件

        Args:
            segments_dir: 包含TS片段的目录
            output_file: 输出的MP4文件路径
            progress_callback: 进度回调函数

        Returns:
            bool: 合并是否成功
        """
        try:
            # 获取所有TS文件并排序
            ts_files = sorted(segments_dir.glob("segment_*.ts"))
            if not ts_files:
                raise Exception("未找到视频片段文件")

            # 创建临时concat文件
            concat_file = segments_dir / "concat_list.txt"

            with open(concat_file, 'w', encoding='utf-8') as f:
                for ts_file in ts_files:
                    # 使用相对路径，避免路径中的特殊字符问题
                    relative_path = ts_file.relative_to(segments_dir)
                    f.write(f"file '{relative_path}'\n")

            # 构建FFmpeg命令
            cmd = [
                self.ffmpeg_path,
                '-f', 'concat',
                '-safe', '0',
                '-i', str(concat_file),
                '-c', 'copy',  # 直接复制流，不重新编码
                '-avoid_negative_ts', 'make_zero',
                '-y',  # 覆盖输出文件
                str(output_file)
            ]

            # 如果需要重新编码（处理兼容性问题）
            if self._needs_reencoding(ts_files[0]):
                cmd = [
                    self.ffmpeg_path,
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', str(concat_file),
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-preset', 'fast',
                    '-crf', '23',
                    '-y',
                    str(output_file)
                ]

            # 执行FFmpeg命令
            await self._run_ffmpeg_with_progress(cmd, len(ts_files), progress_callback)

            # 清理临时文件
            concat_file.unlink(missing_ok=True)

            return output_file.exists()

        except Exception as e:
            raise Exception(f"视频合并失败: {str(e)}")

    def _needs_reencoding(self, sample_file: Path) -> bool:
        """检查是否需要重新编码"""
        try:
            # 使用ffprobe检查视频信息
            probe = ffmpeg.probe(str(sample_file))
            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)

            if not video_stream:
                return True

            # 检查编码格式是否兼容
            codec = video_stream.get('codec_name', '').lower()
            if codec not in ['h264', 'avc']:
                return True

            return False

        except Exception:
            # 无法检查则默认需要重新编码
            return True

    async def _run_ffmpeg_with_progress(self,
                                      cmd: List[str],
                                      total_segments: int,
                                      progress_callback: Optional[Callable[[float], None]]):
        """运行FFmpeg并监控进度"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stderr_data = b''
            while True:
                try:
                    # 读取stderr输出（FFmpeg的进度信息通过stderr输出）
                    chunk = await asyncio.wait_for(process.stderr.read(1024), timeout=1.0)
                    if not chunk:
                        break

                    stderr_data += chunk

                    # 解析进度信息
                    if progress_callback:
                        progress = self._parse_ffmpeg_progress(stderr_data.decode('utf-8', errors='ignore'))
                        if progress >= 0:
                            progress_callback(progress)

                except asyncio.TimeoutError:
                    # 检查进程是否仍在运行
                    if process.returncode is not None:
                        break

            # 等待进程完成
            await process.wait()

            if process.returncode != 0:
                error_msg = stderr_data.decode('utf-8', errors='ignore')
                raise Exception(f"FFmpeg执行失败 (exit code {process.returncode}): {error_msg}")

        except Exception as e:
            if 'process' in locals():
                try:
                    process.terminate()
                    await process.wait()
                except:
                    pass
            raise

    def _parse_ffmpeg_progress(self, stderr_output: str) -> float:
        """解析FFmpeg进度信息"""
        try:
            lines = stderr_output.split('\n')
            for line in reversed(lines):
                if 'time=' in line:
                    # 提取时间信息
                    time_match = line.split('time=')[1].split()[0]
                    # 这里简化处理，实际应该根据总时长计算百分比
                    return min(90.0, len(lines) * 2)  # 简单的进度估算
            return -1
        except:
            return -1

    async def convert_to_mp4(self,
                           input_file: Path,
                           output_file: Path,
                           quality: str = 'medium',
                           progress_callback: Optional[Callable[[float], None]] = None) -> bool:
        """
        转换视频为MP4格式

        Args:
            input_file: 输入视频文件
            output_file: 输出MP4文件
            quality: 质量设置 ('high', 'medium', 'low')
            progress_callback: 进度回调函数

        Returns:
            bool: 转换是否成功
        """
        try:
            # 质量参数映射
            quality_settings = {
                'high': {'crf': '18', 'preset': 'slow'},
                'medium': {'crf': '23', 'preset': 'medium'},
                'low': {'crf': '28', 'preset': 'fast'}
            }

            settings = quality_settings.get(quality, quality_settings['medium'])

            cmd = [
                self.ffmpeg_path,
                '-i', str(input_file),
                '-c:v', 'libx264',
                '-crf', settings['crf'],
                '-preset', settings['preset'],
                '-c:a', 'aac',
                '-b:a', '128k',
                '-movflags', '+faststart',  # 优化网络播放
                '-y',
                str(output_file)
            ]

            await self._run_ffmpeg_with_progress(cmd, 1, progress_callback)
            return output_file.exists()

        except Exception as e:
            raise Exception(f"视频转换失败: {str(e)}")

    async def extract_audio(self,
                          input_file: Path,
                          output_file: Path,
                          format: str = 'mp3') -> bool:
        """
        提取音频

        Args:
            input_file: 输入视频文件
            output_file: 输出音频文件
            format: 音频格式 ('mp3', 'aac', 'wav')

        Returns:
            bool: 提取是否成功
        """
        try:
            format_settings = {
                'mp3': ['-c:a', 'libmp3lame', '-b:a', '192k'],
                'aac': ['-c:a', 'aac', '-b:a', '128k'],
                'wav': ['-c:a', 'pcm_s16le']
            }

            settings = format_settings.get(format, format_settings['mp3'])

            cmd = [
                self.ffmpeg_path,
                '-i', str(input_file),
                '-vn',  # 不包含视频
                *settings,
                '-y',
                str(output_file)
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await process.wait()

            if process.returncode != 0:
                raise Exception(f"音频提取失败 (exit code {process.returncode})")

            return output_file.exists()

        except Exception as e:
            raise Exception(f"音频提取失败: {str(e)}")

    async def get_video_info(self, video_file: Path) -> dict:
        """
        获取视频信息

        Args:
            video_file: 视频文件路径

        Returns:
            dict: 视频信息
        """
        try:
            probe = ffmpeg.probe(str(video_file))

            video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
            audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)

            info = {
                'duration': float(probe['format'].get('duration', 0)),
                'size': int(probe['format'].get('size', 0)),
                'bitrate': int(probe['format'].get('bit_rate', 0)),
                'format_name': probe['format'].get('format_name', ''),
            }

            if video_stream:
                info.update({
                    'width': int(video_stream.get('width', 0)),
                    'height': int(video_stream.get('height', 0)),
                    'video_codec': video_stream.get('codec_name', ''),
                    'fps': eval(video_stream.get('r_frame_rate', '0/1')) or 0,
                })

            if audio_stream:
                info.update({
                    'audio_codec': audio_stream.get('codec_name', ''),
                    'sample_rate': int(audio_stream.get('sample_rate', 0)),
                    'channels': int(audio_stream.get('channels', 0)),
                })

            return info

        except Exception as e:
            raise Exception(f"获取视频信息失败: {str(e)}")

    async def create_thumbnail(self,
                             video_file: Path,
                             output_file: Path,
                             timestamp: float = 5.0,
                             size: str = "320x240") -> bool:
        """
        创建视频缩略图

        Args:
            video_file: 视频文件路径
            output_file: 输出图片文件路径
            timestamp: 截图时间点（秒）
            size: 缩略图尺寸

        Returns:
            bool: 创建是否成功
        """
        try:
            cmd = [
                self.ffmpeg_path,
                '-i', str(video_file),
                '-ss', str(timestamp),
                '-vframes', '1',
                '-s', size,
                '-y',
                str(output_file)
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await process.wait()

            if process.returncode != 0:
                raise Exception(f"缩略图创建失败 (exit code {process.returncode})")

            return output_file.exists()

        except Exception as e:
            raise Exception(f"缩略图创建失败: {str(e)}")

    def check_ffmpeg_availability(self) -> dict:
        """
        检查FFmpeg可用性和支持的编码器

        Returns:
            dict: FFmpeg信息
        """
        try:
            # 检查FFmpeg版本
            result = subprocess.run([self.ffmpeg_path, '-version'],
                                  capture_output=True, text=True, timeout=10)

            if result.returncode != 0:
                return {'available': False, 'error': 'FFmpeg执行失败'}

            version_line = result.stdout.split('\n')[0]

            # 检查编码器支持
            encoders_result = subprocess.run([self.ffmpeg_path, '-encoders'],
                                           capture_output=True, text=True, timeout=10)

            available_encoders = []
            if encoders_result.returncode == 0:
                for line in encoders_result.stdout.split('\n'):
                    if 'libx264' in line:
                        available_encoders.append('H.264')
                    elif 'libx265' in line:
                        available_encoders.append('H.265')
                    elif 'aac' in line:
                        available_encoders.append('AAC')

            return {
                'available': True,
                'version': version_line,
                'path': self.ffmpeg_path,
                'encoders': available_encoders
            }

        except Exception as e:
            return {'available': False, 'error': str(e)}


# 使用示例
async def main():
    processor = FFmpegProcessor()

    # 检查FFmpeg可用性
    info = processor.check_ffmpeg_availability()
    print(f"FFmpeg可用性: {info}")

    if info['available']:
        # 示例：合并视频片段
        segments_dir = Path("./temp_segments")
        output_file = Path("./output.mp4")

        def progress_callback(progress: float):
            print(f"处理进度: {progress:.1f}%")

        try:
            success = await processor.merge_ts_segments(
                segments_dir, output_file, progress_callback
            )
            print(f"合并结果: {'成功' if success else '失败'}")

        except Exception as e:
            print(f"处理失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())