"""Every word the app shows, in Korean and English. Korean is the default.

    tr("key")              text in the current language
    tr("key", days=7)      with {placeholders} filled in
"""
from __future__ import annotations

from datetime import date

LANGUAGES = (("ko", "한국어"), ("en", "English"))   # code, name in its own language
CODES = tuple(code for code, _ in LANGUAGES)
DEFAULT = "ko"
# The bundled Pretendard (TTF: Windows draws it darker and crisper than the OTF). Plain UI text is
# its Medium weight; bold UI text is its own Bold face (Medium has no bold, and a made-up one smears).
UI_FONT_NAME = "Pretendard Medium"
UI_BOLD_NAME = "Pretendard"
UI_FONTS = {"ko": UI_FONT_NAME, "en": UI_FONT_NAME}
UI_BOLD_FONTS = {"ko": UI_BOLD_NAME, "en": UI_BOLD_NAME}
FALLBACK_UI_FONTS = {"ko": "Malgun Gothic", "en": "Segoe UI"}   # used only when Pretendard can't be loaded

_current = DEFAULT


def set_language(code: str) -> str:
    global _current
    _current = code if code in CODES else DEFAULT
    return _current


def language() -> str:
    return _current


def tr(key: str, **values) -> str:
    text = TEXTS[key][CODES.index(_current)]
    return text.format(**values) if values else text


WEEKDAYS = {"ko": ("월", "화", "수", "목", "금", "토", "일"),
            "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")}
WEEK_LETTERS = {"ko": "일월화수목금토", "en": "SMTWTFS"}         # calendar header, Sunday first
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December")


MONTHS_EN_SHORT = tuple(m[:3] for m in MONTHS_EN)
WEEKDAYS_LONG = {"ko": ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"),
                 "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")}

# How dates look in the top bar and on the memo cards (Settings -> date format).
DATE_FORMATS = ("md", "month_day", "iso", "dots", "weekday")
_date_format = DATE_FORMATS[0]


def set_date_format(key: str) -> str:
    global _date_format
    _date_format = key if key in DATE_FORMATS else DATE_FORMATS[0]
    return _date_format


def date_format() -> str:
    return _date_format


def day_label(d: date, fmt: str | None = None, lang: str | None = None, short: bool = False) -> str:
    """``d`` in the chosen date format. ``short`` leaves out the weekday and the year
    (for a narrow note)."""
    fmt, lang = fmt or _date_format, lang or _current
    ko = lang == "ko"
    wd, wd_long = WEEKDAYS[lang][d.weekday()], WEEKDAYS_LONG[lang][d.weekday()]
    month_day = f"{d.month}월 {d.day}일" if ko else f"{MONTHS_EN_SHORT[d.month - 1]} {d.day}"
    if fmt == "month_day":
        return month_day if short else f"{month_day} ({wd})"
    if fmt == "iso":
        return f"{d.month:02d}-{d.day:02d}" if short else d.isoformat()
    if fmt == "dots":
        return f"{d.month}. {d.day}." if short else f"{d.year}. {d.month}. {d.day}. ({wd})"
    if fmt == "weekday":
        if short:
            return month_day
        return f"{wd_long}, {d.month}월 {d.day}일" if ko else f"{wd_long}, {MONTHS_EN[d.month - 1]} {d.day}"
    if short:
        return f"{d.month}/{d.day}"
    return f"{d.month}/{d.day} ({wd})" if ko else f"{d.month}/{d.day} {wd}"


def today_label(d: date, lang: str | None = None) -> str:
    """The default short form, "11/19 (목)", whatever format is chosen (holiday details)."""
    return day_label(d, "md", lang)


def date_row(d: date, lang: str | None = None) -> tuple[str, str]:
    """A note's date row: the day, shown big, and the month and weekday beside it
    ("25", "11월 수요일" / "25", "Wed, Nov"). The date format setting does not change it."""
    lang = lang or _current
    wd = d.weekday()
    if lang == "ko":
        return str(d.day), f"{d.month}월 {WEEKDAYS_LONG['ko'][wd]}"
    return str(d.day), f"{WEEKDAYS['en'][wd]}, {MONTHS_EN_SHORT[d.month - 1]}"


def month_head(year: int, month: int, lang: str | None = None) -> tuple[str, str]:
    """The calendar's head: the month's number, shown big (it names the month: no month name
    beside it), and the year ("11", "2026년" / "11", "2026")."""
    lang = lang or _current
    return str(month), f"{year}년" if lang == "ko" else str(year)


def month_title(year: int, month: int) -> str:
    return f"{year}년 {month}월" if _current == "ko" else f"{MONTHS_EN[month - 1]} {year}"


def week_letters() -> str:
    return WEEK_LETTERS[_current]


def _nth(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def holiday_name(h) -> str:
    """Name of a holidays.Holiday, e.g. "추석", "제9회 전국동시지방선거"."""
    if h.number is not None:
        return tr(f"hol_{h.key}", n=h.number, nth=_nth(h.number))
    return tr(f"hol_{h.key}")


def holiday_detail(h) -> str:
    """One line about it: the lunar date, what it marks, or which day a substitute replaces."""
    if h.replaces is not None:
        return tr("hol_substitute_d", name=holiday_name(h.replaces), day=today_label(h.replaces.day))
    if h.kind == "election":
        return tr("hol_election_d")
    return tr(f"hol_{h.key}_d")


def days_left(days: int) -> str:
    if days <= 0:
        return tr("bin_soon")
    if _current == "en" and days == 1:
        return "1 day left"
    return tr("bin_days_left", days=days)


#        key                       Korean                                   English
TEXTS = {
    # top bar
    "tip_new_memo": ("이 창에서 새 메모 (Ctrl+N)\n지금 메모는 목록에 남아요",
                     "New memo in this window (Ctrl+N)\nthis one stays in the list"),
    "tip_new_window": ("새 노트 창 띄우기 (Ctrl+Shift+N)\n지금 노트 아래 빈자리에 떠요",
                       "Open a new note window (Ctrl+Shift+N)\nit appears in free room under this one"),
    "menu_new_memo": ("이 창에서 새 메모", "New memo in this window"),
    "menu_new_window": ("새 노트 창 띄우기", "Open a new note window"),
    "menu_calendar": ("달력", "Calendar"),
    "menu_on_top": ("항상 위에 표시", "Always on top"),
    "menu_group_drag": ("붙어 있는 노트 같이 끌기 · 크기 맞추기", "Move and resize snapped notes together"),
    "menu_collapse": ("접기", "Fold up"),
    "menu_expand": ("펼치기", "Unfold"),
    "key_double_click": ("더블클릭", "Double-click"),
    "menu_tidy": ("노트 정리", "Tidy up notes"),
    "menu_default_size": ("이 크기를 새 노트 기본 크기로", "Use this size for new notes"),
    "tidy_small": ("작게", "Small"),
    "tidy_medium": ("보통", "Medium"),
    "tidy_large": ("크게", "Large"),
    "tidy_default": ("새 노트 기본 크기", "New-note size"),
    "tidy_keep": ("지금 크기 그대로", "Keep sizes"),
    "tidy_order_place": ("순서: 지금 놓인 대로", "Order: as they are now"),
    "tidy_order_date": ("순서: 메모 날짜 (최근 먼저)", "Order: memo date (newest first)"),
    "tidy_order_pinned": ("순서: 항상 위 노트 먼저", "Order: always-on-top first"),
    "tidied": ("노트를 정리했어요", "Notes tidied up"),
    "calendar_opened": ("달력 자리를 만들었어요", "Made room for the calendar"),
    "resized": ("다른 노트를 비켜 놓았어요", "Moved other notes aside"),
    "grid_moved": ("정렬된 노트를 옮겼어요", "Moved the tiled notes"),
    "resized_together": ("붙은 노트도 맞췄어요", "Snapped notes resized too"),
    "resized_alt_hint": ("Alt: 이 노트만 바꾸기", "Alt: resize just this one"),
    "menu_fold_all": ("모두 접기", "Fold up all"),
    "menu_unfold_all": ("모두 펼치기", "Unfold all"),
    "menu_list": ("메모 목록", "Memo list"),
    "menu_settings": ("설정", "Settings"),
    "menu_style": ("메모 모양…", "Memo layout…"),
    "menu_minimize": ("최소화", "Minimize"),
    "menu_trash": ("이 메모 휴지통으로", "Move this memo to the bin"),
    "tip_more": ("더 보기", "More"),
    "menu_this_month": ("이번 달", "This month"),
    "menu_cal_detach": ("노트에서 떼기", "Detach from note"),
    "menu_cal_attach": ("노트에 붙이기", "Attach to note"),
    "menu_cal_big": ("크게 보기", "Big view"),
    "menu_cal_small": ("작게 보기", "Small view"),
    "tip_unfold": ("펼치기\n위쪽 줄을 더블클릭해도 돼요", "Unfold\nor double-click the top bar"),
    "default_size_set": ("새 노트는 이제 이 크기로 떠요", "New notes now open at this size"),
    "default_size_off": ("새 노트 기본 크기를 해제했어요", "New notes size cleared"),
    "menu_hints": ("조작 안내 다시 보기", "Show the tips again"),
    "menu_detach": ("떼어내기", "Detach"),
    "menu_reopen": ("닫은 노트 열기", "Reopen closed note"),
    "menu_unpin_all": ("모든 노트 고정 풀기", "Unpin all notes"),
    "nothing_closed": ("다시 열 노트가 없어요", "No closed note to reopen"),
    "moved_day": ("날짜를 바꿨어요 · {day}", "Moved to {day}"),
    "hint_title": ("알아두면 편한 조작", "Handy controls"),
    "hint_lines": ("· 위쪽 줄(날짜 포함)을 더블클릭하면 접히고 펼쳐져요\n"
                   "· 붙어 있는 노트는 같이 끌려요 (Alt를 누른 채 끌면 이 노트만)\n"
                   "· 붙은 노트 하나의 크기를 바꾸면 같은 줄·열도 함께 맞춰져요\n"
                   "· 위쪽 줄을 오른쪽 클릭하면 메뉴가 나와요\n"
                   "· 목록 검색칸에서 ↑↓로 고르고 Enter로 열어요\n"
                   "· 큰 달력에서 메모 막대를 다른 날로 끌면 날짜가 바뀌어요\n"
                   "· 달력에서 날짜를 누른 채 다른 날까지 끌면 그 기간의 메모가 생겨요\n"
                   "· 닫은 노트는 Ctrl+Shift+T로 다시 열어요\n"
                   "· 개인 색은 고른 칸을 한 번 더 누르면 다른 색으로 바뀌어요",
                   "· Double-click the top bar (the date too) to fold a note up\n"
                   "· Snapped notes move together (hold Alt to move just one)\n"
                   "· Resizing a snapped note resizes its row and column too\n"
                   "· Right-click the top row for a menu\n"
                   "· In the list's search box, ↑↓ pick a memo and Enter opens it\n"
                   "· In the big calendar, drag a memo to another day to move it\n"
                   "· Drag across days in the calendar to make a memo for that period\n"
                   "· Ctrl+Shift+T reopens a closed note\n"
                   "· Click a chosen personal color again to change it"),
    "hint_ok": ("알겠어요", "Got it"),
    "tip_cal_resize": ("끌어서 달력 크기 바꾸기", "Drag to resize the calendar"),
    "period_days": ("{n}일", "{n} days"),
    "cal_one_day": ("기간 없애기 (첫날 하루만)", "Make it one day (the first)"),
    "one_day_done": ("하루 메모로 바꿨어요", "Now a one-day memo"),
    "peek_count": ("{day} · {i} / {n}   휠: 이전 · 다음 메모", "{day} · {i} of {n}   Wheel: previous · next"),
    "tip_list": ("전체 메모", "All memos"),
    "tip_calendar": ("월 달력", "Month calendar"),
    "tip_close": ("이 노트 닫기 (Ctrl+W)\n(메모는 목록에 남아요)", "Close this note (Ctrl+W)\n(memo stays in the list)"),
    "tip_close_short": ("이 노트 닫기", "Close this note"),
    "tip_minimize": ("최소화", "Minimize"),
    "app_title": ("스티키 노트", "Sticky Note"),
    "set_minimize": ("최소화 방식", "Minimize"),
    "min_fold": ("접기", "Fold away"),
    "min_sticker": ("바탕화면 스티커", "Desktop sticker"),
    "min_bar": ("상단 바만 남기기", "Top bar only"),
    "tip_minimize_style": ("상단 바만 남기기: 노트가 상단 바만 남기고 접혀요. 접힌 상태에서 한 번 더 누르면 사라져요\n"
                           "접기: 노트가 접혀 사라지고, 작업 표시줄 버튼을 누르면 돌아와요\n"
                           "바탕화면 스티커: 노트 자리에 작은 스티커가 남고, 누르면 돌아와요",
                           "Top bar only: the note folds up to its top bar; press again on the bar to hide it\n"
                           "Fold away: the note rolls up and goes; the taskbar button brings it back\n"
                           "Desktop sticker: a small sticker stays where it was; click it to bring it back"),
    "tip_sticker": ("클릭: 노트 다시 열기\n끌어서 옮기기", "Click: open the note again\nDrag to move"),
    "tip_settings": ("설정", "Settings"),
    "set_motion": ("애니메이션", "Animations"),
    "motion_full": ("전체", "Full"),
    "motion_reduced": ("줄이기", "Reduced"),
    "motion_off": ("끄기", "Off"),
    "help_motion": ("창이 움직이고 나타나는 효과예요. 줄이기는 움직임 대신 짧게 흐려지고, 끄기는 바로 바뀌어요",
                    "How windows move and appear. Reduced swaps movement for a short fade; Off changes things at once."),
    "tip_pin": ("항상 위에 표시", "Always on top"),
    "tip_style": ("노트 스타일", "Note style"),
    "tip_trash": ("이 메모를 휴지통으로 이동 (Ctrl+D)\n({days}일 보관, 바로 실행 취소 가능)",
                  "Move this memo to the bin (Ctrl+D)\n(kept {days} days, Undo right after)"),
    "tip_date": ("오늘 · 끌어서 노트 이동\n더블클릭: 접기", "Today · drag to move the note\nDouble-click: fold up"),
    "tip_folded": ("접힌 노트 · 더블클릭하면 펼쳐져요\n{text}", "Folded note · double-click to unfold\n{text}"),
    "folded_pictures": ("[사진 {n}장]", "[{n} pictures]"),
    "tip_back": ("뒤로 (Esc)", "Back (Esc)"),
    "tip_grab": ("끌어서 노트 이동 · 붙어 있는 노트도 같이 움직여요\nAlt를 누른 채 끌면 이 노트만\n더블클릭하면 접기 · 펼치기",
                 "Drag to move the note · notes snapped to it come along\nhold Alt to move only this one\n"
                 "double-click to fold up / unfold"),
    "untitled": ("(빈 메모)", "(empty)"),

    # format bar under the memo
    "tip_bold": ("굵게 (Ctrl+B)", "Bold (Ctrl+B)"),
    "tip_italic": ("기울임꼴 (Ctrl+I)", "Italic (Ctrl+I)"),
    "tip_underline": ("밑줄 (Ctrl+U)", "Underline (Ctrl+U)"),
    "tip_strike": ("취소선 (Ctrl+T)", "Strikethrough (Ctrl+T)"),
    "tip_bullets": ("글머리 기호 (Ctrl+Shift+L)", "Bullets (Ctrl+Shift+L)"),
    "tip_todo": ("할 일 목록 (Ctrl+Shift+C)\n네모를 누르면 완료", "To-do list (Ctrl+Shift+C)\nclick the box when done"),
    "tip_todo_undo": ("완료 취소", "Mark as not done"),
    "tip_todo_remove": ("이 할 일 지우기", "Remove this to-do"),
    "toast_todo_removed": ("할 일을 지웠어요", "To-do removed"),
    "tip_picture": ("사진 추가", "Add pictures"),

    # page titles, undo bar
    "title_list": ("전체 메모", "All memos"),
    "title_settings": ("설정", "Settings"),
    "title_bin": ("휴지통", "Bin"),
    "toast_moved": ("휴지통으로 이동했어요", "Moved to the bin"),
    "cal_new_memo": ("이 날에 새 메모", "New memo on this day"),
    "cal_open": ("열기: {title}", "Open: {title}"),
    "cal_trash": ("휴지통으로", "Move to bin"),
    "tip_period_band": ("이 메모의 기간 · 클릭: 달력에서 보기", "This memo's period · click: see it in the calendar"),
    "undo": ("실행 취소", "Undo"),

    # note styles
    "style_plain": ("기본 (한 줄씩)", "Plain (line by line)"),
    "style_header": ("제목 + 본문", "Header + text"),
    "style_image": ("사진 + 본문", "Image + text"),

    # list page
    "show_all": ("모두 보기", "Show all"),
    "memos_on": ("{day} 메모", "Memos on {day}"),
    "none_on": ("메모 없음", "No memos"),                  # (the day is in the bar above: memos_on)
    "none_found": ("검색 결과가 없어요", "No memos match your search"),
    "none_yet": ("아직 메모가 없어요", "No memos yet"),
    "new_on_day": ("새 메모", "New memo"),                 # (with the add icon before it)
    "open_elsewhere": ("다른 노트에서 열림", "open in another note"),
    "current": ("현재 메모", "current"),
    "bin_count": ("휴지통 ({count})", "Bin ({count})"),
    "bin_empty_short": ("휴지통 (비어 있음)", "Bin (empty)"),
    "tip_bin_link": ("휴지통의 메모는 {days}일 동안 보관돼요", "Memos moved to the bin are kept for {days} days"),
    "tip_card_trash": ("휴지통으로 이동", "Move to bin"),
    "tip_card_pin": ("목록 맨 위에 고정", "Pin to the top of the list"),
    "tip_card_unpin": ("고정 풀기", "Unpin"),
    "pinned_head": ("{n} / {limit}", "{n} / {limit}"),
    "others_head": ("메모", "Memos"),
    "folded_count": ("{head} ({n})", "{head} ({n})"),
    "tip_section": ("누르면 접기 / 펼치기", "Click to fold / unfold"),
    "sort_date": ("날짜순", "By date"),
    "sort_added": ("추가순", "By added"),
    "sort_date_new": ("최근 날짜순", "Newest date first"),
    "sort_date_old": ("오래된 날짜순", "Oldest date first"),
    "sort_added_new": ("최근 추가순", "Newest added first"),
    "sort_added_old": ("오래된 추가순", "Oldest added first"),
    "sort_by_date": ("날짜순 (메모 날짜, 달력에 보이는 날)", "By date (the memo's day on the calendar)"),
    "sort_by_added": ("추가순 (만든 때)", "By when it was added"),
    "sort_newest": ("최근 것부터", "Newest first"),
    "sort_oldest": ("오래된 것부터", "Oldest first"),
    "tip_sort": ("정렬\n누르면 기준(날짜 · 추가)과 순서(최근 · 오래된)를 골라요\n고정된 메모는 고정한 순서 그대로예요",
                 "Order\nClick to choose by date or by added, newest or oldest first\n"
                 "Pinned memos keep the order they were pinned in"),
    "pin_full": ("맨 위 고정은 {n}개까지예요 (설정에서 바꿀 수 있어요)",
                 "Up to {n} pinned memos (change it in Settings)"),
    "pin_off": ("맨 위 고정이 꺼져 있어요 (설정에서 켤 수 있어요)", "Pinning is off (turn it on in Settings)"),

    # menus
    "menu_open": ("열기", "Open"),
    "menu_open_new_window": ("새 노트 창에서 열기", "Open in a new note window"),
    "menu_move_to_bin": ("휴지통으로 이동", "Move to bin"),
    "menu_pin": ("맨 위에 고정", "Pin to top"),
    "menu_unpin": ("고정 풀기", "Unpin"),
    "menu_add_pictures": ("사진 추가…", "Add pictures…"),
    "menu_paste_picture": ("사진 붙여넣기", "Paste picture"),
    "menu_open_picture": ("이 사진 열기", "Open this picture"),
    "menu_remove_picture": ("이 사진 빼기", "Remove this picture"),

    # settings
    "set_color": ("현재 메모 색상", "Current memo color"),
    "set_default_color": ("새 메모 기본 색상", "Default color for new memos"),
    "set_theme_color": ("메인 테마 색 (달력 · 커서)", "Main theme color (calendar, cursor)"),
    "tip_theme_color": ("달력이 이 색을 써요 · 글 커서는 이 색의 보색이에요",
                        "The calendar uses this color · the text cursor takes its opposite"),
    "set_custom_color": ("개인 색 고르기", "Personal color"),
    "tip_custom_color": ("개인 색 · 빈 칸(+)을 누르면 추가\n고른 색을 한 번 더 누르면 다른 색으로 바꾸기",
                         "Personal colors · click + to add one\nclick the chosen one again to change it"),
    "solid_tinted": ("진한 색이라 글이 잘 안 보여서, 바탕은 옅게 칠하고 위 막대와 테두리에 이 색을 써요",
                     "Text is hard to read on this strong color, so the page gets a light tint of it "
                     "and the color goes on the top bar and edge"),
    "solid_kept": ("이 색을 그대로 칠하고 있어요 · 글과 달력 표시가 잘 안 보일 수 있어요",
                   "Painted solid: text and calendar marks may be hard to read"),
    "keep_solid": ("그대로 칠하기", "Keep solid color"),
    "use_tint": ("옅게 칠하기", "Use light tint"),
    "tip_solid": ("이 색 위 글자 대비 {ratio}:1 · 7:1이 안 되는 색은 바탕을 옅게 칠해요",
                  "Text contrast on this color: {ratio}:1 · a color under 7:1 gets a light page"),
    "menu_change_color": ("다른 색으로 바꾸기…", "Change color…"),
    "menu_remove_color": ("이 색 빼기", "Remove this color"),
    "set_transparency": ("투명도", "Transparency"),
    "set_font": ("글꼴", "Font"),
    "set_language": ("언어 (Language)", "Language (언어)"),
    "set_date_format": ("날짜 형식", "Date format"),
    "set_pin_limit": ("목록 맨 위 고정 개수", "Memos pinned to the top of the list"),
    "set_snap": ("노트끼리 붙이기 (자석, 사이 간격)", "Snap notes together (magnet, gap)"),
    "snap_off": ("끄기", "Off"),
    "set_auto_layout": ("자동 레이아웃", "Auto layout"),
    "auto_off": ("끔", "Off"),
    "auto_on": ("켬", "On"),
    "tip_auto_layout": ("켜면: 노트들이 화면 가장자리부터 겹치지 않게 칸칸이 정렬돼요. 많아지면 다 같이 작아져 화면 안에 "
                        "맞춰요 · 끌어서 다른 노트 위에 놓으면 자리 바꾸기 · 노트 하나 크기를 바꾸면 모두 그 크기로 · "
                        "Alt를 누른 채 끌면 그 노트만 정렬에서 빠져요",
                        "On: the notes are tiled from a screen edge, never overlapping; with many they all shrink to "
                        "fit the screen · drop a note on another to swap them · resize one to resize all · "
                        "drag with Alt to take a note out of the tiles"),
    "auto_full": ("화면에 다 들어가지 않아요 · 노트를 접거나 닫아 보세요", "They do not all fit · fold up or close some notes"),
    "tip_snap": ("노트를 끌어 다른 노트 가까이 가면 이 간격으로 붙어요 · Alt를 누른 채 끌면 붙지 않아요",
                 "Dragged near another note, a note snaps to it with this gap · hold Alt to move freely"),
    "today": ("오늘", "Today"),
    "set_cursor": ("글 커서 색", "Text cursor color"),
    "cursor_opposite": ("테마 보색", "Theme's opposite"),
    "cursor_text": ("글자색", "Text color"),
    "set_bin_days": ("휴지통 보관 기간", "Keep memos in the bin for"),
    "bin_day_choice": ("{n}일", "{n} d"),
    "set_export": ("모든 메모를 텍스트로 내보내기…", "Export all memos as text…"),
    "export_title": ("메모 내보내기", "Export memos"),
    "export_name": ("메모", "memos"),
    "export_done": ("메모 {n}개를 내보냈어요", "Exported {n} memos"),
    "export_failed": ("내보내지 못했어요", "Could not export"),
    "export_picture": ("[사진]", "[picture]"),
    "files_text": ("텍스트", "Text"),
    "tip_backups": ("메모는 하루에 한 번 backups 폴더에 복사돼요 (최근 7일)",
                    "Memos are copied to the backups folder once a day (last 7 days)"),
    "set_trash": ("이 메모를 휴지통으로", "Move this memo to the bin"),
    "grp_memo": ("이 메모", "This memo"),
    "grp_look": ("모양 (모든 노트)", "Look (every note)"),
    "grp_place": ("배치", "Arrangement"),
    "grp_general": ("일반", "General"),
    "help_color": ("지금 보고 있는 메모의 색이에요. 다른 노트는 바뀌지 않아요.",
                   "The color of the memo shown here. Other notes keep theirs."),
    "help_font": ("이 메모의 글꼴과 글자 크기예요.", "This memo's font and text size."),
    "help_theme_color": ("달력이 이 색을 쓰고, 글 커서는 이 색의 보색이에요.",
                         "The calendar uses this color; the text cursor takes its opposite."),
    "help_snap": ("노트를 끌어 다른 노트 가까이 가면 이 간격을 두고 붙어요. Alt를 누른 채 끌면 붙지 않아요.",
                  "Dragged near another note, a note snaps to it with this gap. Hold Alt to move freely."),
    "help_auto_layout": ("켜면 노트들이 화면 가장자리부터 겹치지 않게 칸칸이 정렬돼요. 노트가 많아지면 다 같이 작아져 "
                         "화면 안에 맞춰요. Alt를 누른 채 끌면 그 노트만 정렬에서 빠져요.",
                         "On: notes line up from the screen edge without overlapping, and shrink together to fit "
                         "when there are many. Drag with Alt held to take one note out."),
    "help_default_color": ("새로 만드는 메모가 이 색으로 시작해요.", "New memos start in this color."),
    "help_cursor": ("테마 보색은 메인 테마 색의 반대 색이라 눈에 잘 띄어요. 글자색은 글자와 같은 색이에요.",
                    "The theme's opposite color stands out; text color matches the letters."),
    "help_transparency": ("모든 노트에 똑같이 적용돼요. 90%까지 비치게 할 수 있어요.",
                          "One setting for every note, up to 90 %."),
    "help_language": ("앱의 모든 글자가 이 언어로 바뀌어요.", "Every word in the app changes to this language."),
    "help_date_format": ("노트 위쪽과 목록에 이 형식으로 날짜가 보여요.",
                         "Dates show like this on top of the notes and in the list."),
    "help_pin_limit": ("목록 맨 위에 고정할 수 있는 메모 수예요. 0이면 고정하지 않아요.",
                       "How many memos can be pinned to the top of the list. 0: none."),
    "help_bin_days": ("휴지통의 메모는 이 기간이 지나면 완전히 지워져요.",
                      "Memos in the bin are deleted for good after this long."),
    # Settings → General → Update (updater.py)
    "set_update": ("업데이트", "Update"),
    "help_update": ("GitHub에 새 버전이 있는지 확인합니다. 설치는 직접 고를 때만 합니다.",
                    "Checks GitHub for a new version. It installs only when you choose to."),
    "upd_installed": ("설치된 버전 v{v}", "Installed version v{v}"),
    "upd_check": ("업데이트 확인", "Check for updates"),
    "upd_checking": ("확인하는 중…", "Checking…"),
    "upd_latest": ("최신 버전입니다.", "You have the newest version."),
    "upd_new": ("새 버전 v{v}", "New version v{v}"),
    "upd_now": ("지금 업데이트", "Update now"),
    "upd_later": ("나중에", "Not now"),
    "upd_downloading": ("내려받는 중… {pct}%", "Downloading… {pct}%"),
    "upd_installing": ("설치하는 중 — 스티키 노트가 닫혔다가 다시 열립니다.",
                       "Installing — Sticky Note will close and open again."),
    "upd_elsewhere": ("이 사본은 설치 폴더 밖에서 실행 중이라 직접 업데이트할 수 없습니다. "
                      "GitHub에서 새 zip을 받아 설치해 주세요.",
                      "This copy runs outside the install folder, so it can't update itself. "
                      "Get the new zip from GitHub and install it."),
    "upd_done": ("v{v}(으)로 업데이트했습니다.", "Updated to v{v}."),
    "upd_failed": ("업데이트하지 못했습니다. 이전 버전 그대로입니다.",
                   "The update didn't finish. The previous version is still installed."),
    "upd_err_network": ("GitHub에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.",
                        "Couldn't reach GitHub. Check the internet connection and try again."),
    "upd_err_rate": ("GitHub 요청이 너무 많습니다. 잠시 뒤에 다시 시도해 주세요.",
                     "GitHub is getting too many requests. Try again in a while."),
    "upd_err_reply": ("GitHub의 답을 읽지 못했습니다. 나중에 다시 시도해 주세요.",
                      "Couldn't read GitHub's reply. Try again later."),
    "upd_err_download": ("내려받다가 끊겼습니다. 다시 시도해 주세요.", "The download was cut off. Try again."),
    "upd_err_disk": ("디스크 공간이 부족합니다.", "There isn't enough disk space."),
    "upd_err_verify": ("받은 파일이 올바르지 않습니다. 다시 시도해 주세요.",
                       "The downloaded file isn't right. Try again."),
    "upd_err_zip": ("이 버전의 파일에 문제가 있어 설치하지 않았습니다.",
                    "This version's file has a problem, so it wasn't installed."),
    "upd_err_start": ("설치 프로그램을 시작하지 못했습니다.", "Couldn't start the installer."),
    "upd_err_install": ("설치하지 못했습니다: {e}", "Couldn't install: {e}"),
    "color_yellow": ("노랑", "Yellow"),
    "color_orange": ("주황", "Orange"),
    "color_pink": ("분홍", "Pink"),
    "color_purple": ("보라", "Purple"),
    "color_blue": ("파랑", "Blue"),
    "color_green": ("초록", "Green"),
    "color_mint": ("민트", "Mint"),
    "color_white": ("흰색", "White"),
    "color_gray": ("회색", "Gray"),
    "color_charcoal": ("진회색", "Charcoal"),

    # bin page
    "bin_info": ("{days}일 동안 보관한 뒤 삭제돼요.", "Kept for {days} days, then deleted."),
    "bin_empty_button": ("휴지통 비우기", "Empty bin"),
    "bin_is_empty": ("휴지통이 비어 있어요", "The bin is empty"),
    "bin_days_left": ("{days}일 남음", "{days} days left"),
    "bin_soon": ("곧 삭제돼요", "deleting soon"),
    "restore": ("복원", "Restore"),
    "delete_forever": ("영구 삭제", "Delete forever"),
    "confirm_delete": ("한 번 더 누르면 삭제", "Click again to delete"),
    "confirm_empty": ("한 번 더 누르면 비움", "Click again to empty"),

    # calendar
    "tip_prev_month": ("이전 달", "Previous month"),
    "tip_next_month": ("다음 달", "Next month"),
    "tip_close_calendar": ("달력 닫기", "Close calendar"),
    "tip_cal_locked": ("노트에 붙어 있어요 · 위쪽 줄을 끌면 노트와 같이 움직여요 · 누르면 떼기",
                       "Docked to the note · drag its top row to move both · click to undock"),
    "tip_cal_unlocked": ("떨어져 있어요 · 위쪽 줄을 끌어 옮기기 · 누르면 노트에 붙이기",
                         "Undocked · drag its top row to move it · click to dock"),
    "tip_cal_expand": ("크게 보기 (날짜마다 메모 제목)", "Expand (memo titles on each day)"),
    "tip_cal_shrink": ("작게 보기", "Shrink"),
    "calendar_more": ("+{n}개 더", "+{n} more"),
    "tip_today_month": ("오늘로", "Go to today"),
    "calendar_hint": ("날짜 클릭: 그날 메모  ·  더블클릭: 새 메모", "Click a day: its memos  ·  Double-click: new memo"),

    # Korean public holidays (holidays.py): name, then one line of detail
    "hol_new_year": ("신정", "New Year's Day"),
    "hol_new_year_d": ("새해 첫날", "The first day of the year"),
    "hol_seollal_eve": ("설날 연휴", "Seollal holiday"),
    "hol_seollal_eve_d": ("설날 전날 · 음력 섣달 그믐", "The day before Seollal, last day of the lunar year"),
    "hol_seollal": ("설날", "Seollal"),
    "hol_seollal_d": ("음력 1월 1일 · 음력 새해 첫날", "Lunar 1/1 · Lunar New Year's Day"),
    "hol_seollal_after": ("설날 연휴", "Seollal holiday"),
    "hol_seollal_after_d": ("설날 다음 날 · 음력 1월 2일", "The day after Seollal (lunar 1/2)"),
    "hol_march_first": ("3·1절", "Independence Movement Day"),
    "hol_march_first_d": ("국경일 · 1919년 3·1 독립운동을 기념하는 날", "National day · marks the March 1st Movement of 1919"),
    "hol_arbor": ("식목일", "Arbor Day"),
    "hol_arbor_d": ("나무를 심는 날 · 2005년까지 공휴일", "Tree-planting day · a holiday until 2005"),
    "hol_labor": ("노동절", "Labor Day"),
    "hol_labor_d": ("일하는 모든 사람의 날 · 2026년부터 공휴일", "A day for all workers · a public holiday since 2026"),
    "hol_children": ("어린이날", "Children's Day"),
    "hol_children_d": ("어린이를 위한 날", "A day for children"),
    "hol_buddha": ("부처님오신날", "Buddha's Birthday"),
    "hol_buddha_d": ("음력 4월 8일 · 석가모니의 탄생을 기리는 날", "Lunar 4/8 · celebrates the birth of the Buddha"),
    "hol_memorial": ("현충일", "Memorial Day"),
    "hol_memorial_d": ("나라를 위해 목숨을 바친 분들을 기리는 날", "Honors those who gave their lives for the country"),
    "hol_constitution": ("제헌절", "Constitution Day"),
    "hol_constitution_d": ("국경일 · 1948년 헌법 공포를 기념하는 날", "National day · marks the 1948 constitution"),
    "hol_liberation": ("광복절", "Liberation Day"),
    "hol_liberation_d": ("국경일 · 1945년 광복을 기념하는 날", "National day · marks liberation in 1945"),
    "hol_chuseok_eve": ("추석 연휴", "Chuseok holiday"),
    "hol_chuseok_eve_d": ("추석 전날 · 음력 8월 14일", "The day before Chuseok (lunar 8/14)"),
    "hol_chuseok": ("추석", "Chuseok"),
    "hol_chuseok_d": ("음력 8월 15일 · 한가위", "Lunar 8/15 · the harvest moon festival"),
    "hol_chuseok_after": ("추석 연휴", "Chuseok holiday"),
    "hol_chuseok_after_d": ("추석 다음 날 · 음력 8월 16일", "The day after Chuseok (lunar 8/16)"),
    "hol_foundation": ("개천절", "National Foundation Day"),
    "hol_foundation_d": ("국경일 · 단군의 고조선 건국을 기념하는 날", "National day · marks the founding of Gojoseon"),
    "hol_hangul": ("한글날", "Hangul Day"),
    "hol_hangul_d": ("국경일 · 훈민정음 반포를 기념하는 날", "National day · marks the proclamation of Hangul"),
    "hol_christmas": ("기독탄신일", "Christmas Day"),
    "hol_christmas_d": ("성탄절 · 예수의 탄생을 기리는 날", "Celebrates the birth of Jesus"),
    "hol_substitute": ("대체공휴일", "Substitute holiday"),
    "hol_substitute_d": ("{name} {day} 대신 쉬는 날 · 주말이나 다른 공휴일과 겹쳤어요",
                         "Off in place of {name}, {day}, which fell on a weekend or another holiday"),
    "hol_temporary": ("임시공휴일", "Temporary holiday"),
    "hol_temporary_d": ("정부가 따로 정한 공휴일", "A one-off holiday set by the government"),
    "hol_presidential_election": ("제{n}대 대통령 선거", "{nth} presidential election"),
    "hol_general_election": ("제{n}대 국회의원 선거", "{nth} general election"),
    "hol_local_election": ("제{n}회 전국동시지방선거", "{nth} local elections"),
    "hol_election_d": ("선거일 · 투표하는 날", "Election day"),

    # pictures
    "tip_strip": ("사진을 누르면 그 사진과 그 사진의 메모로 바뀌어요 · +로 새 사진(탭) 추가",
                  "Click a picture to switch to it and its own text · + adds a picture as a new tab"),
    "add_picture_bar": ("+  사진 추가", "+  Add picture"),
    "tip_add_picture_bar": ("이 탭의 글 아래에 사진을 넣어요 (새 탭은 위 썸네일 줄의 +)",
                            "Puts a picture under this tab's text (the + by the thumbnails adds a new tab)"),
    "hint_add_pictures": ("클릭하거나 Ctrl+V로 사진 추가", "Click or Ctrl+V to add pictures"),
    "hint_missing_picture": ("사진 파일이 없어요", "Picture file is missing"),
    "choose_pictures": ("사진 고르기", "Choose pictures"),
    "could_not_open": ("열 수 없는 파일:", "Could not open:"),
    "files_images": ("사진", "Images"),
    "files_all": ("모든 파일", "All files"),
}
