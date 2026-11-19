from . import instagram, tiktok, youtube

UPLOADERS = {"youtube": youtube.upload, "tiktok": tiktok.upload, "instagram": instagram.upload}
