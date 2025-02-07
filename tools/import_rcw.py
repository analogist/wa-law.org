import string
import pathlib
import requests_cache
import re
import sqlite3
import sys
import parse
from bs4 import BeautifulSoup
from mdit_py_plugins.anchors.index import slugify

rcw_root_url = "https://apps.leg.wa.gov/rcw/"

requests = requests_cache.CachedSession("rcw_cache")

root = requests.get(rcw_root_url)

soup = BeautifulSoup(root.text, 'html.parser')

sections = soup.find(id="ContentPlaceHolder1_dgSections")
titles = {}
for row in sections.find_all("tr"):
    data = row.find_all("td")
    link = data[0].find("a")
    directory_name = link.text[len("Title "):]
    title_name = data[1].text.strip()
    titles[directory_name] = {"link": link["href"], "title": title_name, "chapters": {}}

all_citations = set()

section_pattern = re.compile("\\(([a-z]+|[0-9]+|[A-Z]+)\\)")

count = 0
for title in titles:
    print("title", title)
    info = titles[title]
    soup = BeautifulSoup(requests.get(rcw_root_url + info["link"]).text, 'html.parser')
    table = soup.find("table")
    for row in table.find_all("tr"):
        link = row.find("a")
        section_info = {}
        data = row.find_all("td")
        info["chapters"][link.text.strip()] = {"link": link["href"] + "&full=true",
                                               "title": data[1].text.strip(),
                                               "sections": section_info}

        chapter = BeautifulSoup(requests.get(link["href"] + "&full=true").text, 'html.parser')
        sections = chapter.find(id="ContentPlaceHolder1_dlSectionContent")
        if not sections:
            continue
        for section in sections.find_all("span"):
            divs = section.find_all("div", recursive=False)
            if not divs:
                continue
            number_link = divs[0].find("a")
            # TODO: Chapter 11.130 has articles to partition sections.
            if not number_link:
                continue
            number = number_link.text
            name = divs[1].h3.text
            full_div = 2
            if "CHANGE IN" in divs[full_div].text:
                full_div = 3
            full_text = [d.text.replace("  ", " ") for d in divs[full_div].find_all("div")]
            citations = []
            section_info[number] = {"title": name, "body": full_text, "citations": citations}
            # print(number, name)
            # if number == "35A.80.010":
            #     print(section)
            #     print("full", full_text)
            if len(divs) == full_div + 1:
                continue
            full_citations = divs[full_div+1].text
            full_citations = full_citations.replace("(i)", "").replace("(ii)", "")
            full_citations = full_citations.replace("(1)", "").replace("(2)", "") 
            full_citations = full_citations.replace(". Prior:", ";")
            raw_citations = full_citations.strip("[] .").split(";")
            if not raw_citations:
                continue
            if ". Formerly RCW" in raw_citations[-1]:
                raw_citations[-1] = raw_citations[-1].split(". Formerly RCW")[0]
            history = [x.strip() for x in raw_citations]
            links = {}
            for link in divs[full_div+1].find_all("a"):
                links[link.text] = link["href"]
            chapter_citations = []
            for citation in history:
                if "repealed by" in citation:
                    cs = citation.strip("()").split(" repealed by ")
                elif "expired" in citation:
                    cs = citation.strip("()").split(" expired ")[:1]
                else:
                    cs = [citation]
                for c in cs:
                    citations.append((c, links.get(c, None)))
                    c = c.strip("()")
                    chapter_citation = c.split("§")[0].strip()
                    all_citations.add(chapter_citation)

            # print()
    #print(titles)
    # if count > 42:
    #     break
    count += 1

ordered = sorted(all_citations)
print("total citations", len(ordered))
# print(ordered[:2000])

def pad_number(n, l):
    if "." not in n:
        prefix = ""
        suffix = n
    else:
        prefix, suffix = n.rsplit(".", maxsplit=1)
        prefix += "."
    pad = ""
    stripped = suffix.strip(string.ascii_uppercase)
    if len(stripped) < l:
        pad = "0" * (l - len(stripped))
    return prefix + pad + suffix

def filename_friendly(n):
    return n.lower().replace(" ", "_").replace(".", "").replace(",", "").replace("/", "_").replace("'", "")

citation_pattern = parse.compile("{year:d} c {chapter:d} § {section:d}")

root = pathlib.Path(sys.argv[1])
top_readme = root / "README.md"
with top_readme.open("w") as rm:
    rm.write("# Revised Code of Washington\n")
    rm.write("Welcome to the Markdown version of the Revised Code of Washington (RCW). It is an *unofficial* copy derived from [the official website](http://apps.leg.wa.gov/rcw/).\n\n")
    for title in titles:
        info = titles[title]
        title_folder_name = pad_number(title, 2) + "_" + filename_friendly(info["title"])
        title_folder = root / title_folder_name
        title_folder.mkdir(exist_ok=True)
        title_readme = title_folder / "README.md"
        rm.write("* [" + title + " - " + info["title"] + "](" + str(title_folder_name) + "/)\n")
        with title_readme.open("w") as tf:
            tf.write("# ")
            tf.write(title + " " + info["title"])
            tf.write("\n\n")

            max_len = 0
            for chapter in info["chapters"]:
                max_len = max(max_len, len(chapter.rsplit(".", maxsplit=1)[-1].strip(string.ascii_uppercase)))
            for chapter in info["chapters"]:
                chapter_info = info["chapters"][chapter]
                chapter_name = pad_number(chapter, max_len) + "_" + filename_friendly(chapter_info["title"]) + ".md"
                chapter_path = title_folder / chapter_name
                link_path = str(chapter_name)
                tf.write("* [" + chapter + " - " + chapter_info["title"] + "](" + link_path + ")\n")
                with chapter_path.open("w") as f:
                    f.write("# " + chapter + " - " + chapter_info["title"] + "\n")

                    for section in chapter_info["sections"]:
                        section_info = chapter_info["sections"][section]
                        full_title = section + " - " + section_info["title"]
                        escaped_title = slugify(full_title)
                        f.write(f"* [{full_title}](#{escaped_title})\n")

                    for section in chapter_info["sections"]:
                        section_info = chapter_info["sections"][section]
                        f.write("## ")
                        f.write(section)
                        f.write(" - ")
                        f.write(section_info["title"])
                        f.write("\n")
                        last_group = ""
                        indents = []
                        for paragraph in section_info["body"]:
                            last_end = 0
                            for result in section_pattern.finditer(paragraph):
                                if result.start() != last_end:
                                    break
                                if last_end > 0:
                                    f.write(" [Empty]\n\n")
                                last_end = result.end()
                                group = result.group(1)
                                suffix = "."
                                if group.isnumeric():
                                    depth = 0
                                elif ((group[0] == "i" and last_group != "h") or
                                      (group[0] == "v" and last_group != "u") or
                                      (group[0] == "x" and last_group != "w")):
                                    depth = 2
                                elif ((group[0] == "I" and last_group != "H") or
                                      (group[0] == "V" and last_group != "U") or
                                      (group[0] == "X" and last_group != "W")):
                                    depth = 4
                                elif group.isupper():
                                    depth = 3
                                    suffix = ". "
                                else:
                                    depth = 1

                                while len(indents) > depth:
                                    indents.pop()

                                f.write(" " * sum(indents) + group + suffix )
                                indents.append(len(group) + len(suffix) + 1)
                                last_group = group
                            f.write(paragraph[last_end:])
                            f.write("\n\n")
                        f.write("\\[ ")
                        for citation in section_info["citations"]:
                            if citation[1]:
                                escaped_link = citation[1].replace(" ", "%20")
                                f.write(f"[{citation[0]}]({escaped_link}); ")
                                parsed = citation_pattern.parse(citation[0])
                                # TODO: Link to our own page of session law.
                                # if not parsed:
                                #     print(citation)
                            else:
                                f.write(f"{citation[0]}; ")

                        f.write("\\]\n\n")

