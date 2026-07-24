#!/bin/bash
# Agiten.app 빌드 — SwiftUI 소스를 컴파일해 .app 번들로 묶는다.
#   사용:  bash macapp/build_app.sh
#   결과:  macapp/Agiten.app  (더블클릭 실행)
set -e
cd "$(dirname "$0")/.."          # 저장소 루트

APP="macapp/Agiten.app"
BIN="$APP/Contents/MacOS/Agiten"
RES="$APP/Contents/Resources"

echo "› 이전 빌드 정리"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES"

echo "› Swift 컴파일"
# -parse-as-library: @main 을 앱 진입점으로 인식시킨다
swiftc -parse-as-library -O \
    -o "$BIN" \
    macapp/AgitenApp.swift \
    -framework SwiftUI -framework AppKit

echo "› Info.plist 작성"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Agiten</string>
  <key>CFBundleDisplayName</key><string>Agiten</string>
  <key>CFBundleIdentifier</key><string>com.hobak.agiten</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>Agiten</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
</dict>
</plist>
PLIST

echo "› 아이콘"
# 간단한 이모지 아이콘을 텍스트로 렌더 → icns (실패해도 앱은 동작)
python3 - <<'PY' 2>/dev/null || true
# 로봇 이모지를 PNG로 그려 icon 후보 저장(선택 사항)
try:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA",(512,512),(23,26,33,255))
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Apple Color Emoji.ttc", 300)
    except Exception:
        f = None
    d.text((256,256),"🤖",anchor="mm",font=f,embedded_color=True)
    img.save("macapp/Agiten.app/Contents/Resources/icon.png")
except Exception:
    pass
PY

echo "› 애드혹 코드사인 (게이트키퍼 경고 완화)"
codesign --force --deep -s - "$APP" 2>/dev/null || echo "  (사인 생략 — 첫 실행 시 우클릭→열기 필요할 수 있음)"

echo ""
echo "✓ 완성: $APP"
echo "  실행:  open $APP     또는 Finder에서 더블클릭"
