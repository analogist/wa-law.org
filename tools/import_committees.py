import cached_session
from bs4 import BeautifulSoup, NavigableString
import re
import pathlib
import sys
import subprocess
import arrow

FORCE_FETCH = True

api_root_url = "http://wslwebservices.leg.wa.gov"
csi_root_url = "https://app.leg.wa.gov/csi"

requests = cached_session.CustomCachedSession("committee_cache")

committee_path = pathlib.Path("bill/")

meetings_by_bill = {}

TESTIFY_REMOTE = 'I would like to testify remotely'
TESTIFY_NOTED = 'I would like my position noted for the legislative record'
TESTIFY_WRITTEN = 'I would like to submit written testimony'

def add_lines(lines, active, heard, inactive):
    if active:
        lines.append("Active bills:")
        lines.extend(active)
        lines.append("")
    if heard:
        lines.append("Heard bills:")
        lines.extend(heard)
        lines.append("")
    if inactive:
        lines.append("")
        lines.append("<details>")
        lines.append("    <summary>Click to view inactive bills</summary>")
        lines.append("")
        lines.extend(inactive)
        lines.append("</details>")
        lines.append("")


for start_year in range(2021, 2023, 2):
    biennium = f"{start_year:4d}-{(start_year+1) % 100:02d}"
    print(biennium)

    url = api_root_url + f"/CommitteeMeetingService.asmx/GetCommitteeMeetings?beginDate={start_year}-01-01&endDate={start_year+1}-12-31"
    print(url)
    meetings = requests.get(url, force_fetch=FORCE_FETCH)
    meetings = BeautifulSoup(meetings.text, "xml")
    count = 0
    for info in meetings.find_all("CommitteeMeeting"):
        count += 1
        agendaId = info.AgendaId.text
        # print(info.AgendaId.text, info.Date.text, info.RevisedDate.text)
        url = api_root_url + f"/CommitteeMeetingService.asmx/GetCommitteeMeetingItems?agendaId={agendaId}"
        # print(url)
        items = requests.get(url)
        items = BeautifulSoup(items.text, "xml")
        for item in items.find_all("CommitteeMeetingItem"):
            billId = item.BillId.text
            if billId:
                bill_number = billId.split(" ")[1]
                if bill_number not in meetings_by_bill:
                    meetings_by_bill[bill_number] = []
                meetings_by_bill[bill_number].append((arrow.get(info.Date.text), info, item))
            else:
                # print(item)
                pass

    print("-----")
    now = arrow.now()
    active = {}
    heard = {}
    for bill_number in meetings_by_bill:
        meetings = meetings_by_bill[bill_number]
        meetings.sort(key=lambda x: x[0])

        activity = ""

        for dt, meeting, item in meetings:
            if now < dt:
                if not activity:
                    activity = item.HearingTypeDescription.text + " " + dt.format("ddd, MMM D h:mm a")
                # print(activity)
                # print(item)
                # print(meeting)
                # doc link: https://app.leg.wa.gov/committeeschedules/Home/Documents/29441
                mId = meeting.AgendaId.text
                # print("[live]()") # tId=2
                # print("[written]()") # tId=4
                # print("[+/-]()") # tId=3

                url = csi_root_url + f"/Home/GetAgendaItems/?chamber=House&meetingFamilyId={mId}"
                agendaItems = requests.get(url)
                items = BeautifulSoup(agendaItems.text, "html")
                for item in items.find_all(class_="agendaItem"):
                    if bill_number not in item.text:
                        continue
                    chamber, mId, aId, caId = [x.strip(" ')") for x in item["onclick"].split(",")[1:]]
                    url = csi_root_url + f"/{chamber}/TestimonyTypes/?chamber={chamber}&meetingFamilyId={mId}&agendaItemFamilyId={aId}&agendaItemId={caId}"
                    testimonyOptions = requests.get(url)
                    testimonyOptions = BeautifulSoup(testimonyOptions.text, "html")
                    testimony_links = {}
                    for option in testimonyOptions.find_all("a"):
                        testimony_links[option.text] = option["href"]

                    biennium_path = pathlib.Path(f"bill/{biennium}")
                    bill_path = list(biennium_path.glob(f"*/{bill_number}/README.md"))
                    if bill_path and bill_path[0].exists():
                        bill_path = bill_path[0]
                        new_lines = []
                        in_testify = False
                        testify_removed = False
                        for line in bill_path.read_text().split("\n"):
                            if line.startswith("#"):
                                in_testify = line == "## Testify"
                                if not in_testify:
                                    new_lines.append(line)
                                else:
                                    testify_removed = True
                            elif in_testify:
                                pass
                            else:
                                new_lines.append(line)
                        if not testify_removed:
                            new_lines.append("")
                        new_lines.append("## Testify")
                        committee = meeting.LongName.text
                        testify_date = dt.format("ddd, MMM D") + " at " + dt.format("h:mm a")
                        new_lines.append(f"The {committee} committee will be holding a public hearing on {testify_date}. There are three ways to testify. You can do more than one.")
                        new_lines.append(f"* 👍 / 👎 [Sign in support or oppose a bill.](https://app.leg.wa.gov{testimony_links[TESTIFY_NOTED]})")
                        new_lines.append(f"* ✍️ [Provide written feedback on a bill.](https://app.leg.wa.gov{testimony_links[TESTIFY_WRITTEN]})")
                        new_lines.append(f"* 📺 [Sign up to give live testimony over Zoom.](https://app.leg.wa.gov{testimony_links[TESTIFY_REMOTE]})")
                        new_lines.append("")
                        new_lines.append(f"Testimony is public record. You can see who is signed up to testify [on the website](https://app.leg.wa.gov/csi/Home/GetOtherTestifiers/?agendaItemId={caId}).")
                        bill_path.write_text("\n".join(new_lines))
            else:
                if item.HearingType.text != "Public":
                    continue
                mId = meeting.AgendaId.text
                url = csi_root_url + f"/Home/GetAgendaItems/?chamber=House&meetingFamilyId={mId}"
                agendaItems = requests.get(url)
                items = BeautifulSoup(agendaItems.text, "lxml")
                for item in items.find_all(class_="agendaItem"):
                    if bill_number not in item.text:
                        continue
                    chamber, mId, aId, caId = [x.strip(" ')") for x in item["onclick"].split(",")[1:]]

                    url = csi_root_url + f"/Home/GetOtherTestifiers/?agendaItemId={caId}"
                    testifiers = requests.get(url)
                    testifiers = BeautifulSoup(testifiers.text, "lxml")
                    totals = {}
                    for row in testifiers.find_all("tr"):
                        cols = [c.text for c in row.find_all("td")]
                        if not cols:
                            continue
                        stance = cols[3]
                        if stance not in totals:
                            totals[stance] = 0
                        totals[stance] += 1
                    if bill_number in heard:
                        for k in totals:
                            if k in heard[bill_number]:
                                heard[bill_number][k] += totals[k]
                            else:
                                heard[bill_number][k] = totals[k]
                    else:
                        heard[bill_number] = totals

        if activity:
            active[bill_number] = activity

        # 
        # https://app.leg.wa.gov
    print(count, "meetings")
    print(len(active), "active bills")

    bill_index = pathlib.Path(f"bill/{biennium}/README.md")
    new_lines = []
    active_lines = []
    inactive_lines = []
    heard_lines = []
    heading = None
    for line in bill_index.read_text().split("\n"):
        if line.startswith("#"):
            heading = line
            # add active/inactive sections
            add_lines(new_lines, active_lines, heard_lines, inactive_lines)
            active_lines = []
            heard_lines = []
            inactive_lines = []
            new_lines.append(line)
            pass
        elif line.startswith("*"):
            if heading == "# 2021-22":
                new_lines.append(line)
                continue
            # parse out bill number and bin
            bill_number = line.split()[2][:4]
            if "|" in line:
                line = line.split("|")[0][:-1]
            thumbs = ""
            if bill_number in heard:
                pro = heard[bill_number].get("Pro", 0)
                con = heard[bill_number].get("Con", 0)
                other = heard[bill_number].get("Other", 0)
                thumbs = f" **{pro}👍** **{con}👎** **{other}❓**"
            if bill_number in active:
                active_lines.append(line + " | *" + active[bill_number] + "*" + thumbs)
            elif bill_number in heard:
                heard_lines.append(line + f" |" + thumbs)
            else:
                inactive_lines.append(line)
            pass
        elif line.strip().startswith("<") or line.startswith("Active bills") or line.startswith("Heard bills"):
            # Skip any <details> or <summary> that we've already added.
            pass
        elif line:
            new_lines.append(line)

    add_lines(new_lines, active_lines, heard_lines, inactive_lines)
    bill_index.write_text("\n".join(new_lines))