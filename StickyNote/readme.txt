스티키 노트

설치
1. zip 파일의 압축을 풉니다. (zip 안에서 바로 실행하면 설치되지 않습니다.)
2. 풀린 StickyNote 폴더에서 "install.cmd"를 두 번 클릭합니다.
   보안 경고 창이 뜨면 "실행"을 누릅니다. ("Windows의 PC 보호" 창이면 "추가 정보" → "실행")
   관리자 권한을 묻는 창(사용자 계정 컨트롤)이 뜨면 "예"를 누릅니다.
   ("아니요"를 눌러도 괜찮습니다: 관리자 권한 없이 내 사용자 폴더에 그대로 설치됩니다.)
3. 바탕화면과 시작 메뉴에 "스티키 노트" 바로가기가 생기고 앱이 바로 시작됩니다.
   설치가 끝나면 압축을 푼 폴더와 zip 파일은 지워도 됩니다.

새 버전으로 바꿀 때
v1.1.0부터는 앱 안에서 바꿉니다: 설정 → 일반 → 업데이트에서 "업데이트 확인"을 누르고,
새 버전이 있으면 "지금 업데이트"를 누릅니다. 앱이 닫혔다가 새 버전으로 다시 열립니다.
(앱은 이 버튼을 누를 때만 GitHub를 확인하고, "지금 업데이트"를 누를 때만 설치합니다.)
예전처럼 새 zip으로 위의 설치를 반복해도 됩니다. 어느 쪽이든 메모는 그대로 남습니다.

파일 위치
프로그램: %LOCALAPPDATA%\Programs\StickyNote
메모: %APPDATA%\StickyNote (notes.json, images 폴더)

지우려면
"스티키 노트" 바로가기 두 개(바탕화면, 시작 메뉴)와 %LOCALAPPDATA%\Programs\StickyNote 폴더를 지웁니다.
메모까지 지우려면 %APPDATA%\StickyNote 폴더도 지웁니다.

앱은 Python Software Foundation이 서명한 pythonw.exe로 실행됩니다.
사용한 구성 요소(Python, Tcl/Tk, Pillow, Pretendard 글꼴)의 라이선스는 licenses 폴더에 있습니다.
Pretendard 글꼴은 앱 안에서만 쓰며 Windows에 설치하지 않습니다.
