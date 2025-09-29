import re
import requests
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import base64


@dataclass
class M3U8Segment:
    uri: str
    duration: float
    sequence: int
    key_uri: Optional[str] = None
    key_iv: Optional[bytes] = None
    byte_range: Optional[Tuple[int, int]] = None


@dataclass
class M3U8Playlist:
    base_url: str
    segments: List[M3U8Segment]
    target_duration: float
    total_duration: float
    is_encrypted: bool = False
    encryption_method: Optional[str] = None
    key_uri: Optional[str] = None
    key_iv: Optional[bytes] = None


class M3U8Parser:
    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.headers = headers or {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def parse_m3u8(self, url: str) -> M3U8Playlist:
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            content = response.text

            # 解析master playlist还是media playlist
            if '#EXT-X-STREAM-INF' in content:
                return self._parse_master_playlist(url, content)
            else:
                return self._parse_media_playlist(url, content)

        except Exception as e:
            raise Exception(f"解析M3U8失败: {str(e)}")

    def _parse_master_playlist(self, url: str, content: str) -> M3U8Playlist:
        lines = content.strip().split('\n')
        base_url = self._get_base_url(url)

        playlists = []
        current_stream_info = None

        for line in lines:
            line = line.strip()
            if line.startswith('#EXT-X-STREAM-INF:'):
                current_stream_info = self._parse_stream_inf(line)
            elif line and not line.startswith('#') and current_stream_info:
                playlist_url = urljoin(base_url, line)
                bandwidth = current_stream_info.get('BANDWIDTH', 0)
                resolution = current_stream_info.get('RESOLUTION', '')
                playlists.append({
                    'url': playlist_url,
                    'bandwidth': int(bandwidth),
                    'resolution': resolution
                })
                current_stream_info = None

        # 选择最高质量的流
        if playlists:
            best_playlist = max(playlists, key=lambda x: x['bandwidth'])
            return self.parse_m3u8(best_playlist['url'])

        raise Exception("未找到可用的媒体流")

    def _parse_media_playlist(self, url: str, content: str) -> M3U8Playlist:
        lines = content.strip().split('\n')
        base_url = self._get_base_url(url)

        segments = []
        target_duration = 0
        sequence = 0

        current_key_uri = None
        current_key_iv = None
        current_duration = 0
        encryption_method = None

        for i, line in enumerate(lines):
            line = line.strip()

            if line.startswith('#EXT-X-TARGETDURATION:'):
                target_duration = float(line.split(':')[1])

            elif line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
                sequence = int(line.split(':')[1])

            elif line.startswith('#EXT-X-KEY:'):
                key_info = self._parse_key_line(line)
                encryption_method = key_info.get('METHOD')
                if encryption_method == 'AES-128':
                    current_key_uri = key_info.get('URI', '').strip('"')
                    if current_key_uri:
                        current_key_uri = urljoin(base_url, current_key_uri)

                    iv_hex = key_info.get('IV', '').replace('0x', '')
                    if iv_hex:
                        current_key_iv = bytes.fromhex(iv_hex)

            elif line.startswith('#EXTINF:'):
                duration_match = re.search(r'#EXTINF:([0-9.]+)', line)
                if duration_match:
                    current_duration = float(duration_match.group(1))

            elif line and not line.startswith('#'):
                segment_url = urljoin(base_url, line)

                segment = M3U8Segment(
                    uri=segment_url,
                    duration=current_duration,
                    sequence=sequence,
                    key_uri=current_key_uri,
                    key_iv=current_key_iv or self._generate_iv(sequence)
                )

                segments.append(segment)
                sequence += 1
                current_duration = 0

        total_duration = sum(seg.duration for seg in segments)
        is_encrypted = encryption_method == 'AES-128'

        return M3U8Playlist(
            base_url=base_url,
            segments=segments,
            target_duration=target_duration,
            total_duration=total_duration,
            is_encrypted=is_encrypted,
            encryption_method=encryption_method,
            key_uri=current_key_uri
        )

    def _parse_stream_inf(self, line: str) -> Dict[str, str]:
        result = {}

        # 解析带宽
        bandwidth_match = re.search(r'BANDWIDTH=(\d+)', line)
        if bandwidth_match:
            result['BANDWIDTH'] = bandwidth_match.group(1)

        # 解析分辨率
        resolution_match = re.search(r'RESOLUTION=(\d+x\d+)', line)
        if resolution_match:
            result['RESOLUTION'] = resolution_match.group(1)

        return result

    def _parse_key_line(self, line: str) -> Dict[str, str]:
        result = {}

        # 解析METHOD
        method_match = re.search(r'METHOD=([^,\s]+)', line)
        if method_match:
            result['METHOD'] = method_match.group(1)

        # 解析URI
        uri_match = re.search(r'URI="([^"]+)"', line)
        if uri_match:
            result['URI'] = uri_match.group(1)

        # 解析IV
        iv_match = re.search(r'IV=([^,\s]+)', line)
        if iv_match:
            result['IV'] = iv_match.group(1)

        return result

    def _get_base_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{'/'.join(parsed.path.split('/')[:-1])}/"

    def _generate_iv(self, sequence: int) -> bytes:
        return sequence.to_bytes(16, byteorder='big')

    def get_encryption_key(self, key_uri: str) -> bytes:
        try:
            response = self.session.get(key_uri, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise Exception(f"获取加密密钥失败: {str(e)}")

    def decrypt_segment(self, encrypted_data: bytes, key: bytes, iv: bytes) -> bytes:
        try:
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

            # 移除PKCS7填充
            padding_length = decrypted[-1]
            return decrypted[:-padding_length]
        except Exception as e:
            raise Exception(f"解密视频片段失败: {str(e)}")


if __name__ == "__main__":
    parser = M3U8Parser()

    # 测试用例
    test_url = "https://example.com/playlist.m3u8"
    try:
        playlist = parser.parse_m3u8(test_url)
        print(f"解析成功: {len(playlist.segments)} 个片段")
        print(f"总时长: {playlist.total_duration:.2f} 秒")
        print(f"是否加密: {playlist.is_encrypted}")
    except Exception as e:
        print(f"解析失败: {e}")