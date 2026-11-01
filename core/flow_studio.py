"""
Flow Studio — Canvas kéo-thả image-to-video theo Mục 7 và 8.4 của đặc tả.
- Canvas nền chấm (dot grid), các thẻ video nổi trên canvas kéo-thả tự do.
- Mỗi thẻ bắt đầu từ một ảnh đầu vào + ô prompt riêng có @tag.
- Nút 'Tạo tất cả' đưa mọi thẻ chưa tạo vào cùng cơ chế dispatcher của Mục 2.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.queue_manager import queue_manager

from core.paths import DATA_DIR, STUDIO_FILE


class StudioCard:
    def __init__(
        self,
        card_id: str,
        image_url: str,
        prompt: str = "",
        x: int = 40,
        y: int = 40,
        status: str = "chưa tạo",  # "chưa tạo", "đang tạo", "đã tạo", "lỗi"
        job_id: str = "",
        video_url: str = "",
        thumbnail_url: str = "",
        quality_badge: str = "HD",
        error: str = "",
        created_at: float | None = None,
    ):
        self.id = card_id
        self.image_url = image_url
        self.prompt = prompt
        self.x = x
        self.y = y
        self.status = status
        self.job_id = job_id
        self.video_url = video_url
        self.thumbnail_url = thumbnail_url
        self.quality_badge = quality_badge
        self.error = error
        self.created_at = created_at or time.time()

    def to_dict(self) -> Dict[str, Any]:
        # Tự động đồng bộ trạng thái từ job trong hàng đợi nếu có
        if self.job_id:
            job = queue_manager.get_job(self.job_id)
            if job:
                if job.status == "Hoàn thành":
                    self.status = "đã tạo"
                    self.video_url = job.video_url
                    self.thumbnail_url = job.thumbnail_url
                elif job.status == "Đang chạy":
                    self.status = "đang tạo"
                elif job.status == "Thất bại":
                    self.status = "lỗi"
                    self.error = job.error

        return {
            "id": self.id,
            "imageUrl": self.image_url,
            "prompt": self.prompt,
            "x": self.x,
            "y": self.y,
            "status": self.status,
            "jobId": self.job_id,
            "videoUrl": self.video_url,
            "thumbnailUrl": self.thumbnail_url,
            "qualityBadge": self.quality_badge,
            "error": self.error,
            "createdAt": self.created_at,
        }


class FlowStudioManager:
    def __init__(self, storage_path: Path = STUDIO_FILE):
        self.storage_path = storage_path
        self.cards: Dict[str, StudioCard] = {}
        self.load()

    def load(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            for item in raw:
                c = StudioCard(
                    card_id=item["id"],
                    image_url=item.get("imageUrl", ""),
                    prompt=item.get("prompt", ""),
                    x=item.get("x", 40),
                    y=item.get("y", 40),
                    status=item.get("status", "chưa tạo"),
                    job_id=item.get("jobId", ""),
                    video_url=item.get("videoUrl", ""),
                    thumbnail_url=item.get("thumbnailUrl", ""),
                    quality_badge=item.get("qualityBadge", "HD"),
                    error=item.get("error", ""),
                    created_at=item.get("createdAt"),
                )
                self.cards[c.id] = c
        except Exception as e:
            print(f"[FlowStudioManager] Lỗi đọc studio.json: {e}")

    def save(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self.cards.values()]
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_card(self, image_url: str, prompt: str = "", x: int | None = None, y: int | None = None) -> StudioCard:
        """Tạo thẻ mới trên canvas từ một ảnh đầu vào, vị trí không chồng thẻ cũ (Mục 8.4)."""
        card_id = f"card_{uuid.uuid4().hex[:8]}"

        # Tính toán vị trí mặc định tránh chồng chéo
        if x is None or y is None:
            count = len(self.cards)
            cols = 3
            col = count % cols
            row = count // cols
            x = 60 + col * 360
            y = 60 + row * 460

        card = StudioCard(
            card_id=card_id,
            image_url=image_url,
            prompt=prompt,
            x=x,
            y=y,
            status="chưa tạo",
        )
        self.cards[card_id] = card
        self.save()
        return card

    def update_card(self, card_id: str, patch: Dict[str, Any]) -> Optional[StudioCard]:
        """Cập nhật prompt, vị trí kéo-thả, ảnh đầu vào của một thẻ."""
        card = self.cards.get(card_id)
        if not card:
            return None

        if "prompt" in patch:
            card.prompt = patch["prompt"]
        if "x" in patch:
            card.x = int(patch["x"])
        if "y" in patch:
            card.y = int(patch["y"])
        if "imageUrl" in patch:
            card.image_url = patch["imageUrl"]
        if "status" in patch:
            card.status = patch["status"]

        self.save()
        return card

    def delete_card(self, card_id: str) -> bool:
        if card_id in self.cards:
            self.cards.pop(card_id)
            self.save()
            return True
        return False

    def list_cards(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self.cards.values()]

    def generate_all_studio(self, duration: int = 15, ratio: str = "9:16") -> List[str]:
        """Đưa mọi thẻ chưa tạo / bị lỗi vào dispatcher dùng chung (Mục 7.3 & 8.4)."""
        cards_to_run = [
            c for c in self.cards.values()
            if c.status in ("chưa tạo", "lỗi")
        ]
        job_ids = []
        for card in cards_to_run:
            prompt = card.prompt.strip() or "Biến chuyển động từ ảnh tham chiếu, cinematic 4k"
            job_id_list = queue_manager.enqueue_batch(
                prompts=[prompt],
                duration=duration,
                ratio=ratio,
            )
            if job_id_list:
                jid = job_id_list[0]
                card.job_id = jid
                card.status = "đang tạo"
                job_ids.append(jid)

        self.save()
        return job_ids


flow_studio = FlowStudioManager()
