"""Tests for P3-4: PII filter detection and redaction."""


from app.core.pii_filter import filter_pii, has_pii

# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


def test_has_pii_detects_email():
    assert has_pii("联系我 user@example.com 获取更多信息") is True


def test_has_pii_detects_phone():
    assert has_pii("我的手机是 13812345678，随时联系") is True


def test_has_pii_detects_ip():
    assert has_pii("服务器地址 192.168.1.100 已下线") is True


def test_has_pii_no_false_positive():
    """Clean text without PII should return False."""
    assert has_pii("CS2 是一款优秀的射击游戏") is False
    assert has_pii("Elden Ring has great reviews") is False


# ---------------------------------------------------------------------------
# Redaction tests
# ---------------------------------------------------------------------------


def test_filter_pii_redacts_email():
    result = filter_pii("联系我 user@example.com 获取更多信息")
    assert "user@example.com" not in result
    assert "[EMAIL_REDACTED]" in result


def test_filter_pii_redacts_phone():
    result = filter_pii("我的手机是 13812345678，随时联系")
    assert "13812345678" not in result
    # Phone should be partially masked: 138****5678
    assert "****" in result


def test_filter_pii_redacts_bearer_token():
    result = filter_pii("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxx")
    assert "eyJhbGci" not in result
    assert "[TOKEN_REDACTED]" in result


def test_filter_pii_clean_text_unchanged():
    text = "CS2 的在线玩家数量在过去一周保持稳定"
    result = filter_pii(text)
    assert result == text
