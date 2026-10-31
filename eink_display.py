"""JSAUX E-INK Bluetooth LE display link protocol.

Host application-layer framing over Nordic UART-style GATT characteristics
for connect, device-info query, and image transfer.

Chip firmware / OTA update protocols are NOT included.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Optional


def _bleak():
    from bleak import BleakClient, BleakScanner

    return BleakClient, BleakScanner


# BLE UUIDs
SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
WRITE_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NOTIFY_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

# 协议常量
HEADER_CMD = 0xAC  # APP 发送的包头
FOOTER_CMD = 0xCA  # APP 发送的包尾
HEADER_RSP = 0x91  # 设备响应的包头
FOOTER_RSP = 0x19  # 设备响应的包尾

# 命令码
CMD_QUERY_INFO = 0x00  # query device info
CMD_SEND_DATA = 0x02  # send display image payload
# CMD_OTA / chip-firmware flashing is intentionally omitted from this tree.

# 显示区域
DISPLAY_A = 0x00  # A面
DISPLAY_B = 0x01  # B面
DISPLAY_AB = 0x02  # AB两面

# Target panel geometry used by the host app
TARGET_WIDTH = 648
TARGET_HEIGHT = 480
TARGET_COLOR_MODE = 0
TARGET_IS_DUAL_SCREEN = False


def parse_response_frame(raw: bytes, command: int) -> Optional[bytes]:
    """Return the payload of a complete notification frame for ``command``."""
    frame = bytes(raw or b"")
    if len(frame) < 4 or frame[0] != HEADER_RSP or frame[1] != command or frame[-1] != FOOTER_RSP:
        return None
    return frame[2:-1]


class DataAckStatus(Enum):
    MISSING = "missing"
    SUCCESS = "success"
    REJECTED = "rejected"
    INVALID = "invalid"


def data_ack_status(raw: Optional[bytes]) -> DataAckStatus:
    """Classify a data-ACK notification without accepting malformed frames."""
    if raw is None:
        return DataAckStatus.MISSING
    frame = bytes(raw)
    if len(frame) < 2 or frame[0] != HEADER_RSP or frame[1] != CMD_SEND_DATA:
        return DataAckStatus.MISSING
    payload = parse_response_frame(frame, CMD_SEND_DATA)
    if payload == b"\x00":
        return DataAckStatus.SUCCESS
    if payload == b"\x01":
        return DataAckStatus.REJECTED
    return DataAckStatus.INVALID


def build_display_data_packet(index: int, payload: bytes, payload_size: int) -> bytes:
    """Build one display-data frame using the payload size announced by the device."""
    if not 0 <= index <= 0xFFFF:
        raise ValueError("packet index is outside the protocol range")
    if payload_size <= 0 or len(payload) > payload_size:
        raise ValueError("invalid display payload length")
    return (
        bytes([HEADER_CMD, CMD_SEND_DATA, (index >> 8) & 0xFF, index & 0xFF])
        + payload.ljust(payload_size, b"\x00")
        + bytes([FOOTER_CMD])
    )


def is_eink_name(name: Optional[str]) -> bool:
    """Match current and legacy EInk advertisement names."""
    normalized = " ".join((name or "").strip().upper().replace("_", " ").split())
    return normalized == "JSAUX E-INK"


@dataclass
class DeviceInfo:
    """设备信息"""

    is_dual_screen: bool  # 是否双屏
    color_mode: int  # 颜色模式: 0=2色, 1=3色, 2=4色, 4=6色, 8=7色
    width: int  # 屏幕宽度(像素)
    height: int  # 屏幕高度(像素)
    packet_size: int  # 每包数据大小(字节)
    battery: int  # 电量百分比

    @property
    def color_count(self) -> int:
        """返回颜色数量"""
        color_map = {0: 2, 1: 3, 2: 4, 4: 6, 8: 7}
        return color_map.get(self.color_mode, 2)

    def __str__(self):
        screen_type = "双屏" if self.is_dual_screen else "单屏"
        return (
            f"屏幕: {self.width}x{self.height}, {screen_type}, "
            f"{self.color_count}色, 电量: {self.battery}%"
        )


class EInkDisplay:
    """墨水屏控制类"""

    def __init__(self, address: str):
        self.address = address
        self.client = None
        self.device_info: Optional[DeviceInfo] = None
        self._response_event = asyncio.Event()
        self._response_data: bytes = b""
        self._expected_response_command: Optional[int] = None
        self._command_lock = asyncio.Lock()
        self._data_ack_notifications: Optional[bool] = None

    async def connect(self) -> bool:
        """连接设备"""
        self.client = _bleak()[0](self.address)
        try:
            await self.client.connect()
            # 订阅通知
            await self.client.start_notify(NOTIFY_UUID, self._on_notify)
            print(f"已连接到 {self.address}")
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("已断开连接")

    def _on_notify(self, sender, data: bytearray):
        """处理设备通知"""
        expected_command = self._expected_response_command
        if expected_command is None:
            return
        if expected_command == CMD_SEND_DATA:
            if data_ack_status(data) is DataAckStatus.MISSING:
                return
        elif parse_response_frame(data, expected_command) is None:
            return
        self._response_data = bytes(data)
        self._response_event.set()

    async def _send_command(
        self, data: bytes, command: int, timeout: float = 5.0
    ) -> Optional[bytes]:
        async with self._command_lock:
            return await self._send_command_locked(data, command, timeout)

    async def _send_command_locked(
        self,
        data: bytes,
        command: int,
        timeout: float = 5.0,
        report_timeout: bool = True,
    ) -> Optional[bytes]:
        """发送命令并等待响应"""
        if not self.client or not self.client.is_connected:
            print("未连接设备")
            return None

        self._response_event.clear()
        self._expected_response_command = command
        try:
            await self.client.write_gatt_char(WRITE_UUID, data, response=True)
            await asyncio.wait_for(self._response_event.wait(), timeout)
            return self._response_data
        except asyncio.TimeoutError:
            if report_timeout:
                print("等待响应超时")
            return None
        finally:
            self._expected_response_command = None

    async def query_info(self, display: int = DISPLAY_AB) -> Optional[DeviceInfo]:
        """查询设备信息"""
        async with self._command_lock:
            return await self._query_info_locked(display)

    async def _query_info_locked(self, display: int) -> Optional[DeviceInfo]:
        cmd = bytes([HEADER_CMD, CMD_QUERY_INFO, display, FOOTER_CMD])
        response = await self._send_command_locked(cmd, CMD_QUERY_INFO)

        payload = parse_response_frame(response, CMD_QUERY_INFO) if response else None
        if payload is None or len(payload) != 9:
            print(f"响应无效: {response}")
            return None

        self.device_info = DeviceInfo(
            is_dual_screen=(payload[0] == 0x00),
            color_mode=payload[1],
            width=(payload[2] << 8) | payload[3],
            height=(payload[4] << 8) | payload[5],
            packet_size=(payload[6] << 8) | payload[7],
            battery=payload[8],
        )
        return self.device_info

    async def send_image_data(self, image_bytes: bytes, display: int = DISPLAY_A) -> bool:
        """
        发送图片数据到墨水屏
        image_bytes: 处理后的图像数据(黑白二值)
        """
        async with self._command_lock:
            if not self.device_info:
                await self._query_info_locked(display)

            if not self.device_info:
                print("无法获取设备信息")
                return False

            packet_size = self.device_info.packet_size
            total_packets = (len(image_bytes) + packet_size - 1) // packet_size

            print(f"开始发送 {len(image_bytes)} 字节, 共 {total_packets} 包")

            for i in range(total_packets):
                start = i * packet_size
                end = min(start + packet_size, len(image_bytes))
                chunk = image_bytes[start:end]

                packet = build_display_data_packet(i, chunk, packet_size)
                if self._data_ack_notifications is False:
                    await self.client.write_gatt_char(WRITE_UUID, packet, response=True)
                    continue

                response = await self._send_command_locked(
                    packet,
                    CMD_SEND_DATA,
                    timeout=0.5 if self._data_ack_notifications is None else 5.0,
                    report_timeout=self._data_ack_notifications is True,
                )
                ack_status = data_ack_status(response)
                if ack_status is DataAckStatus.REJECTED:
                    print(f"第 {i + 1} 包被设备拒绝: {bytes(response or b'').hex()}")
                    return False
                if ack_status is DataAckStatus.INVALID:
                    print(f"第 {i + 1} 包确认帧无效: {bytes(response or b'').hex()}")
                    return False
                if ack_status is DataAckStatus.SUCCESS:
                    self._data_ack_notifications = True
                else:
                    was_notification_mode = self._data_ack_notifications is True
                    self._data_ack_notifications = False
                    if was_notification_mode:
                        print("数据通知确认缺失，切换为 GATT Write 响应确认传输")
                    else:
                        print("未收到数据通知确认，使用 GATT Write 响应确认传输")

            # 进度显示
            if (i + 1) % 50 == 0 or i == total_packets - 1:
                print(f"进度: {i + 1}/{total_packets}")

        print("图片发送完成!")
        return True


async def find_display() -> Optional[str]:
    """扫描并返回墨水屏的 BLE 地址"""
    print("正在扫描墨水屏...")
    devices = await _bleak()[1].discover(timeout=5.0)

    for d in devices:
        if is_eink_name(d.name):
            display = EInkDisplay(d.address)
            if not await display.connect():
                continue
            try:
                info = await display.query_info()
            finally:
                await display.disconnect()

            if not info:
                continue
            if (
                info.width == TARGET_WIDTH
                and info.height == TARGET_HEIGHT
                and info.color_mode == TARGET_COLOR_MODE
                and info.is_dual_screen == TARGET_IS_DUAL_SCREEN
            ):
                print(f"Found JSAUX E-INK display: {d.name} ({d.address})")
                return d.address
            print(f"跳过非目标墨水屏: {d.name} ({d.address}) - {info}")

    print("未找到墨水屏，请确保设备已开启")
    return None


# 测试代码
async def main():
    address = await find_display()
    if not address:
        return

    display = EInkDisplay(address)
    if await display.connect():
        info = await display.query_info()
        if info:
            print(f"设备信息: {info}")
        await display.disconnect()


if __name__ == "__main__":
    asyncio.run(main())


def build_query_info_command(display: int) -> bytes:
    """Build query-info command frame."""
    return bytes([HEADER_CMD, CMD_QUERY_INFO, display, FOOTER_CMD])


def parse_device_info_payload(raw: bytes):
    """Parse device-info bytes from notify/advertising payloads."""
    data = bytes(raw or b"")
    marker = data.find(bytes([HEADER_RSP, CMD_QUERY_INFO]))
    if marker < 0 or len(data) < marker + 12:
        return None
    payload = parse_response_frame(data[marker: marker + 12], CMD_QUERY_INFO)
    if payload is None or len(payload) != 9:
        return None
    return DeviceInfo(
        is_dual_screen=(payload[0] == 0x00),
        color_mode=payload[1],
        width=(payload[2] << 8) | payload[3],
        height=(payload[4] << 8) | payload[5],
        packet_size=(payload[6] << 8) | payload[7],
        battery=max(0, min(100, payload[8])),
    )


def firmware_update_supported() -> bool:
    """Chip firmware / OTA protocol is not open-sourced and not implemented."""
    return False


async def start_firmware_update(*_args, **_kwargs):
    """Firmware flashing is unavailable in the open-source tree."""
    raise NotImplementedError(
        "Chip firmware / OTA protocol is not provided in this open-source tree."
    )


# Host touchscreen panel input identity used by desktop controller.
TOUCHSCREEN_NAMES = ("FTS3528:00 2808:1015",)
