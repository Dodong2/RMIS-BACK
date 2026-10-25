"""Rich text (the TipTap HTML of proposal Sections II, IV, VI, VIII, IX; client 2026-10-23) as plain lines for the
downloaded forms, which render text in PDF, DOCX, XLSX and CSV alike. Paragraphs and headings become lines, list items
"• " or "1. ", table rows "cell | cell". Text without tags is returned unchanged.

rich_text_lines() drops bold/italic/underline (CSV, Excel). rich_text_marks() gives the same lines escaped, keeping them
as <b>, <i> and <u> for the SF-018 PDF and Word (Carl 2026-10-25, Task 9); links and strikethrough stay plain text."""
import re
from html.parser import HTMLParser
from xml.sax.saxutils import escape

HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "div"}
MARKS = {"strong": "b", "b": "b", "em": "i", "i": "i", "u": "u"}
EMPTY_MARK = re.compile(r"<([biu])>(\s*)</\1>")


def _squeeze(text):
    return re.sub(r"\s+", " ", text).strip()


class _Lines(HTMLParser):
    def __init__(self, marks=False):
        super().__init__(convert_charrefs=True)
        self.marks = marks
        self.open = []  # marks open at this point, outermost first
        self.lines = []
        self.text = ""  # the line being collected
        self.prefix = ""  # "• " / "1. " of the list item being collected
        self.lists = []  # [tag, items so far] per open list
        self.cells = None  # cells of the table row being collected

    def collected(self):
        """The line so far; a mark still open is closed here and reopened on the next line."""
        text = self.text + "".join(f"</{m}>" for m in reversed(self.open))
        while self.marks and EMPTY_MARK.search(text):
            text = EMPTY_MARK.sub(r"\2", text)
        self.text = "".join(f"<{m}>" for m in self.open)
        return _squeeze(text)

    def visible(self, text):
        return HTML_TAG.sub("", text) if self.marks else text

    def end_line(self):
        text = self.collected()
        if self.visible(text):
            self.lines.append(self.prefix + text)
            self.prefix = ""

    def handle_starttag(self, tag, attrs):
        if self.marks and tag in MARKS:
            self.open.append(MARKS[tag])
            self.text += f"<{MARKS[tag]}>"
            return
        if self.cells is not None and tag not in ("tr", "td", "th"):
            return  # paragraphs inside a cell stay in the cell
        if tag in ("ul", "ol"):
            self.end_line()
            self.lists.append([tag, 0])
        elif tag == "li":
            self.end_line()
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            self.prefix = "  " * max(len(self.lists) - 1, 0) + ("• " if kind[0] == "ul" else f"{kind[1]}. ")
        elif tag == "tr":
            self.end_line()
            self.cells = []
        elif tag == "br" or (tag in BLOCKS and not self.prefix):
            self.end_line()

    def handle_endtag(self, tag):
        if self.marks and tag in MARKS:
            if MARKS[tag] in self.open:
                self.open.reverse()
                self.open.remove(MARKS[tag])
                self.open.reverse()
                self.text += f"</{MARKS[tag]}>"
            return
        if tag in ("td", "th") and self.cells is not None:
            self.cells.append(self.collected())
        elif tag == "tr":
            if self.cells and any(self.visible(cell) for cell in self.cells):
                self.lines.append(" | ".join(self.cells))
            self.cells = None
            self.collected()
        elif self.cells is not None:
            return
        elif tag in ("ul", "ol"):
            self.end_line()
            if self.lists:
                self.lists.pop()
        elif tag == "li" or tag in BLOCKS:
            self.end_line()

    def handle_data(self, data):
        self.text += escape(data) if self.marks else data


def _parse(value, marks):
    parser = _Lines(marks)
    parser.feed(value)
    parser.close()
    parser.end_line()
    return "\n".join(parser.lines)


def rich_text_lines(value):
    """Readable text for a form section; plain text (no tags) comes back as it was saved."""
    if not value or not HTML_TAG.search(value):
        return value
    return _parse(value, marks=False)


def rich_text_marks(value):
    """The same lines as rich_text_lines(), escaped, with bold/italic/underline as <b>/<i>/<u>."""
    if not value or not HTML_TAG.search(value):
        return escape(value) if value else value
    return _parse(value, marks=True)
