# Photo Viewer v1.0.1

Photo Viewer는 Windows용 이미지·영상 뷰어이자 폴더 탐색기입니다. 로컬 및 SMB/UNC 폴더 탐색, 단일·2장·3장·웹툰 보기, 애니메이션 이미지, VLC 기반 영상 재생을 지원합니다.

## 다운로드

최신 설치 파일은 [GitHub Releases](https://github.com/StynerPark/Photo-Viewer/releases/latest)에서 받을 수 있습니다.

- 설치 파일: `PhotoViewer_v1.0.1_Setup.exe`
- 이전 등록 정리 도구: `PhotoViewer_DefaultApp_Reset_v1.0.1.exe`
- Windows 10/11 x64
- 현재 배포 파일은 코드 서명이 없으므로 Windows SmartScreen 안내가 표시될 수 있습니다.

## v1.0.1 핵심 변경

- 설치형 제품명, 창 제목, 실행 파일과 Windows 메타데이터를 `Photo Viewer` / `PhotoViewer.exe`로 통일했습니다.
- 설정은 `%LocalAppData%\Photo Viewer\settings.json`에 저장합니다.
- 기존 `%LocalAppData%\Portable Photo Viewer\settings.json`은 새 설정이 없을 때 한 번 자동 복사합니다.
- 설치 완료 후 Windows 기본 앱 설정 화면을 자동으로 열지 않습니다.
- 설치할 이미지 확장자 39개를 사용자가 선택할 수 있으며 영상 확장자는 등록하지 않습니다.
- 사용자용과 전체 사용자용 중복 설치를 차단합니다.
- 연결된 이미지를 더블클릭하면 뷰어가 전면으로 열립니다.
- 단일·2장·3장 영상 슬롯의 재생, 무한 반복과 빠른 영상 전환을 유지합니다.
- 뷰어 삭제 후 탐색기로 강제 전환하지 않고 다음 미디어를 계속 표시합니다.
- 탐색기 폴더 트리 구조와 사용자가 조절한 스플리터 크기를 유지합니다.
- 폴더 진입·복귀·탭 전환·썸네일·모드 전환 작업의 비동기 처리와 취소 로직을 유지합니다.
- 웹툰 모드의 원본 종횡비, 가시 영역 우선 로딩과 제한된 캐시를 유지합니다.
- 처음/끝에서 휠·PageUp·PageDown 입력은 현재 미디어를 다시 로드하지 않는 no-op입니다.

전체 변경 이력은 [CHANGELOG.md](CHANGELOG.md)를 참고하십시오.

## 지원 형식

이미지:

`apng`, `avif`, `avifs`, `bmp`, `bw`, `dds`, `gif`, `icb`, `ico`, `j2c`, `j2k`, `jfif`, `jp2`, `jpc`, `jpe`, `jpeg`, `jpf`, `jpg`, `jpx`, `pbm`, `pcx`, `pgm`, `png`, `pnm`, `ppm`, `psd`, `qoi`, `ras`, `rgb`, `rgba`, `sgi`, `tga`, `tif`, `tiff`, `vda`, `vst`, `webp`, `xbm`, `xpm`

영상:

`mp4`, `mkv`, `avi`, `mov`, `webm`, `wmv`, `flv`, `m4v`, `mpeg`, `mpg`, `ts`, `m2ts`, `3gp`, `ogv`

압축 파일: `zip`

## 주요 기능

- Windows 스타일 폴더 트리, 다중 탭, 주소 입력과 빠른 검색
- 상세·목록·중간·큰 아이콘 보기와 이름·크기·형식·날짜 정렬
- 단일·더블·트리플·웹툰 뷰어 모드
- GIF, Animated WebP, APNG 재생
- VLC/libVLC 영상 재생, 탐색, 음량, 정지와 무한 반복
- 이미지 확대·축소·회전·맞춤과 잠금
- 복사·잘라내기·붙여넣기·이름 변경·휴지통 삭제
- 라이트/다크 테마와 사용자 단축키
- 단일/다중 인스턴스 실행

## 설치 및 연결

설치기는 현재 사용자 또는 모든 사용자를 선택하고, 설치 경로와 연결 후보 이미지 확장자를 지정할 수 있습니다. Windows 10/11은 기본 앱 확정을 사용자 선택으로 보호하므로 필요한 경우 이미지 파일을 더블클릭하고 `Photo Viewer`를 선택하십시오.

이전 공개판이나 시험판의 등록을 먼저 지우려면 릴리스의 `PhotoViewer_DefaultApp_Reset_v1.0.1.exe`를 실행하십시오. 사진, 사용자 설정과 다른 앱 등록은 삭제하지 않습니다.

## 소스 실행

```powershell
python -m pip install -r requirements.txt
python main.py
```

영상 재생에는 VLC 3.x x64 런타임이 필요합니다. `main.py` 옆의 `vlc` 폴더 또는 `PMV_VLC_SOURCE` 환경 변수로 런타임 경로를 제공합니다.

## EXE 빌드

```powershell
$env:PHOTO_VIEWER_VLC_SOURCE = 'C:\path\to\vlc'
python build_exe.py
```

결과는 `dist\PhotoViewer\PhotoViewer.exe`에 생성됩니다. 설치기 빌드에는 Inno Setup 7이 필요하며 `installer\PhotoViewer.iss`를 컴파일합니다.

## 테스트

```powershell
python tests/run_all.py
```

회귀 테스트는 미디어 끝점 no-op, 빠른 탐색, 웹툰 비율, 애니메이션 워커, 탐색기 복원, 세션 모드, 전면 실행, 뷰어 삭제, UI 구조, 탭 상태, 비동기 스캔·썸네일·VLC와 무한 반복을 검사합니다.
