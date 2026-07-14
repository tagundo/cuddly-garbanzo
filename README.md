# youtube_gen — SIFAS/스쿠스타 YouTube 설명 생성기

SIFAS(스쿠스타) MOD/MV 영상용 **다국어(일본어·한국어·영어) YouTube 제목/설명**을
클릭 몇 번으로 만들어 주는 도구입니다.

곡 · 아티스트(그룹/솔로) · 의상 · MOD · 화면비 등을 고르면 언어별 제목과
재생목록 줄, 해시태그를 자동으로 조합하고, 그대로 복사할 수 있습니다.

이전에는 PySide6(Qt) 데스크톱 앱이었지만, 지금은 `sifas_fbx.py`와 동일하게
**브라우저 기반**입니다. 파이썬 표준 라이브러리만으로 로컬 서버를 띄우므로
별도 설치가 필요 없고, 휴대폰·원격 브라우저에서도 접속할 수 있습니다.

## 실행

```bash
python3 youtube_gen_v20.py
```

가능하면 독립 앱 창(pywebview)으로, 아니면 브라우저 창으로 UI가 열립니다.
아무것도 업로드되지 않으며, 모든 데이터는 내 컴퓨터에만 저장됩니다.

### 옵션

```bash
python3 youtube_gen_v20.py --no-browser      # 창을 열지 않고 서버만 (원격/헤드리스)
python3 youtube_gen_v20.py --port 8780        # 포트 지정 (기본: 자동)
python3 youtube_gen_v20.py --host 0.0.0.0     # 다른 기기에서 접속 허용
python3 youtube_gen_v20.py --data other.json  # 다른 데이터 파일 사용
```

### 명령줄에서 한 줄 생성 (헤드리스)

```bash
python3 youtube_gen_v20.py generate \
    --atype groups --artist Muse \
    --song "Snow halation" --costume "All Stars Next" \
    --ratio 16:9 --vtype MOD --mods "Shorter Skirt"
```

### 자체 점검

```bash
python3 youtube_gen_v20.py selftest
```

## 데이터

- 모든 항목은 스크립트 옆 **`youtube_data.json`** 에 저장됩니다.
- 저장은 **원자적 쓰기**로 이루어지고, 세션 첫 저장·수동 백업·Import 시점에
  **번호 순환 백업**(`youtube_data_1.json` … `_5.json`)을 남깁니다.
  (일반 자동 저장은 백업을 새로 만들지 않아 백업이 금방 밀려나지 않습니다.)
- 상단 버튼: **저장**(수동 저장), **백업**(지금 백업), **Import JSON**(비파괴 병합),
  **Export**(현재 데이터 내려받기).

## 요구 사항

- Python 3.8+ (표준 라이브러리만 사용)
- 선택: `pywebview` — 브라우저 탭 대신 독립 앱 창으로 열고 싶을 때
  (없으면 자동으로 브라우저 창으로 대체됩니다)
