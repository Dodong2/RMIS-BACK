"""Rich text (the TipTap HTML of proposal Sections II, IV, VI, VIII, IX; client 2026-10-23) as plain lines for the
downloaded forms, which render text in PDF, DOCX, XLSX and CSV alike. Paragraphs and headings become lines, list items
"• " or "1. ", table rows "cell | cell". Bold/italic/underline are dropped. Text without tags is returned unchanged."""
import re
from html.parser import HTMLParser

HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "div"}


def _squeeze(text):
    return re.sub(r"\s+", " ", text).strip()


class _Lines(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.text = ""  # the line being collected
        self.prefix = ""  # "• " / "1. " of the list item being collected
        self.lists = []  # [tag, items so far] per open list
        self.cells = None  # cells of the table row being collected

    def end_line(self):
        text = _squeeze(self.text)
        if text:
            self.lines.append(self.prefix + text)
            self.prefix = ""
        self.text = ""

    def handle_starttag(self, tag, attrs):
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
        if tag in ("td", "th") and self.cells is not None:
            self.cells.append(_squeeze(self.text))
            self.text = ""
        elif tag == "tr":
            if self.cells and any(self.cells):
                self.lines.append(" | ".join(self.cells))
            self.cells, self.text = None, ""
        elif self.cells is not None:
            return
        elif tag in ("ul", "ol"):
            self.end_line()
            if self.lists:
                self.lists.pop()
        elif tag == "li" or tag in BLOCKS:
            self.end_line()

    def handle_data(self, data):
        self.text += data


def rich_text_lines(value):
    """Readable text for a form section; plain text (no tags) comes back as it was saved."""
    if not value or not HTML_TAG.search(value):
        return value
    parser = _Lines()
    parser.feed(value)
    parser.close()
    parser.end_line()
    return "\n".join(parser.lines)
