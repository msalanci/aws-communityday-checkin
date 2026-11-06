<!-- Copyright (c) 2026-2027 Michal Salanci. SPDX-License-Identifier: MIT -->

# Community Day check-in

Check-in with name stickers for a one-day community event that sells (or gives away) its tickets in [pretix](https://pretix.eu).

At the entrance, volunteers scan each attendee's ticket QR code with their phone. The ticket is checked in at pretix, and a Brother label printer next to the desk prints a sticker with the attendee's name, which goes on their badge. Scanning the same ticket again shows "Already checked in at 09:14"; a cancelled or fake ticket shows "Not valid".

```
 Phone (browser)                AWS (your account)                         pretix
 ┌──────────────┐  HTTPS   ┌──────────────────────────┐   check in   ┌───────────┐
 │ scanner page │ ───────► │ API Gateway + Lambda     │ ───────────► │ your event│
 └──────────────┘          │ at checkin.<your domain> │              └───────────┘
                           └────────────┬─────────────┘
                                        │ print request (name only)
                                        ▼
                                ┌───────────────┐   USB   ┌─────────────────────┐
                                │ SQS queue     │ ◄─────  │ Windows PC + Brother│
                                └───────────────┘  pulls  │ QL-820NWB printer   │
                                                          └─────────────────────┘
```

AWS keeps no attendee database: pretix holds the registrations, and a name exists in AWS only for the seconds its print request waits in the queue. The cost is a few cents for the day, plus the domain.

There are three places you work in:
- **pretix**, in the browser: the event, its check-in list and an API token;
- **the admin computer** (macOS or Linux): deploys everything to AWS and stores the settings;
- **the print PC** (Windows): runs the program that prints the stickers.

---

## 1. What you need

### Accounts

| What | Notes |
|---|---|
| **pretix** organizer account | [pretix.eu](https://pretix.eu) (hosted) or your own pretix server. On pretix.eu a new organizer account is reviewed by hand before a shop can go live: **start this first**, it is the slowest step. Turn on two-factor authentication. |
| **AWS account** | With an admin user or role you can use from the AWS CLI. Everything runs in this one account. |
| **A domain** | Any domain you control, with its DNS at any provider. The scanner page gets its own address, `checkin.<your domain>`. Terraform writes the page's DNS records into a public Route 53 hosted zone in this AWS account: either your domain's own zone, if it is already in Route 53 here, or a small zone just for `checkin.<your domain>`, which you hand over from your DNS provider with one NS record (below). Terraform only adds records; it never changes the zone itself. |

**If your domain's DNS is not in Route 53 in this account** (another DNS provider, or Route 53 in another AWS account), hand just the page's own name, for example `checkin.example.org`, over to this account. Your domain stays where it is:

1. In this AWS account, create a public hosted zone for that name:
   ```bash
   aws route53 create-hosted-zone --name checkin.example.org --caller-reference "$(date +%s)"
   ```
   The answer lists the zone's four name servers (`DelegationSet.NameServers`).
2. At your DNS provider, in the zone `example.org`, add an **NS** record named `checkin` with those four name servers.
3. Check that it works (it can take a few minutes): `dig NS checkin.example.org +short` shows the four AWS name servers.
4. In step 3.3 set `domain_name = "checkin.example.org"` and `subdomain = ""`. The page is then `https://checkin.example.org`.

The zone costs $0.50 a month. If you ever delete it, remove the NS record at your DNS provider first, or someone else could claim the name.

### The admin computer (macOS or Linux)

| Tool | Version | Check with |
|---|---|---|
| Terraform | 1.17 | `terraform version` |
| AWS CLI | v2, with credentials for your account | `aws sts get-caller-identity` |
| Python | 3.10 or later (the scripts use it for small JSON jobs) | `python3 --version` |
| bash, curl, uuidgen, zip, unzip, git | any recent | already on macOS and most Linux |

The scripts and Terraform use the AWS CLI's **default** credentials. To use another profile, run `export AWS_PROFILE=<name>` in that terminal first.

### The print PC and the printer

| What | Notes |
|---|---|
| A PC with **Windows 11, x64** | Not Windows on ARM: Brother has no drivers for it. You need admin rights for the installs and a free USB port. |
| **Brother QL-820NWB** label printer with its USB cable | The program talks to it through Brother's b-PAC SDK, over USB. |
| A label roll, for example **DK-22205** (62 mm continuous paper) | Printed in landscape: the 62 mm are the sticker's height, and you choose its length. Pick a length that fits the blank space on your badges. |

### Phones

Any **Android phone with Chrome**, or an **iPhone with Safari** (iOS 16 or later). Open the page in the browser itself, from a bookmark or by typing the address, not from inside a chat app: their built-in browsers often have no camera access.

---

## 2. pretix: the event, its check-in list and a token

### 2.1 Create the event

Create the event as a **single event**: leave "This is an event series" unchecked. pretix asks only once, in the creation wizard, and it cannot be changed later.

Then set:

| Setting | Value | Why |
|---|---|---|
| Attendee names | Asked **per ticket**, **required** | The name on the sticker comes from the ticket |
| Name format | **Given name, family name** | The sticker prints them as one or two lines |
| Email | Required | pretix sends the ticket by email |
| Tickets per order | 1 | One name per order keeps it simple |
| Products | For example one free product, "Attendee", without approval | |
| Ticket code generator | Leave the default (random). **Never change it after registration opens**, or QR codes already sent may stop working | |
| Invoicing → "Ask for invoice address" | **Off** | Checkout then asks only for the email and the name |

### 2.2 Make sure the email carries the QR code

The QR code is only in the **PDF ticket attached** to the confirmation email, never in the email's text. That needs four settings:

1. Settings → Tickets → **"Allow users to download tickets"**: on (off by default).
2. On the same page, the **PDF** ticket output: enabled.
3. On the same page, **"Download date"**: empty.
4. Settings → E-mail → **"Attach ticket files"**: on.

Check with one test registration (next section): the confirmation email has a PDF with a QR code.

### 2.3 The check-in list, and testing

pretix creates a check-in list with every event. Open it in your event: **Check-in → Check-in lists → the default list**, and set:
- **all products** included;
- **"Allow multiple entries"**: off (a ticket checks in once);
- **"Include pending orders"**: off.

Write down two values from your browser's address bar:

| Value | Where | Example |
|---|---|---|
| **Organizer slug** | `https://pretix.eu/control/organizer/<slug>/…` | `my-community` |
| **Check-in list ID** | the number at the end of the list's address, `…/checkinlists/<id>/` | `123456` |

**Testing:** while your shop is in **test mode**, register yourself as a test attendee in your own shop. Each test ticket checks in only once, so register another one whenever you need a fresh ticket. When the shop goes live, let pretix delete the orders made in test mode. Test registrations made after that are real free orders: cancel them before the event.

### 2.4 An API token

The AWS side calls pretix with an API token:

1. Open `https://pretix.eu/control/organizer/<slug>/teams` (your organizer → Teams).
2. Click the team the token should belong to. A team with access to your event and permission to check in is enough. A team with full rights works too, but then the token can do anything in your organizer account.
3. Scroll down to **API tokens**, type a name such as `lambda`, and click the button next to it.
4. pretix shows the token **once**. Keep it at hand for step 3.5; it goes straight into AWS and nowhere else.

---

## 3. The admin computer: deploy and configure

All commands below run from the root of this repository.

### 3.1 Get the code and check AWS

```bash
git clone <this repository's URL> community-day-checkin
cd community-day-checkin
aws sts get-caller-identity        # shows the account you will deploy to
```

### 3.2 The state bucket (once)

Terraform keeps its state in an S3 bucket. A small separate configuration, the bootstrap, creates that bucket. Its own state is a local file, which you keep outside this repository.

```bash
cd infrastructure/bootstrap
cp terraform.tfvars.example terraform.tfvars    # set state_bucket_name: globally unique, e.g. my-event-tf-state
cp backend.hcl.example backend.hcl              # set path: a folder outside this repository
terraform init -backend-config=backend.hcl
terraform apply
cd ../..
```

The bucket is versioned, encrypted, private and protected from `terraform destroy`; keep it for next year.

### 3.3 The app (certificate, API, Lambdas, queue)

```bash
cd infrastructure
cp terraform.tfvars.example terraform.tfvars    # set domain_name, and anything else from the table below
cp backend.hcl.example backend.hcl              # set bucket: the bucket from 3.2
terraform init -backend-config=backend.hcl
terraform plan
terraform apply                                 # the certificate takes a few minutes
cd ..
```

| Variable | Default | Meaning |
|---|---|---|
| `domain_name` | — (required) | Your Route 53 zone, e.g. `example.org`, or `checkin.example.org` for a zone made just for the page |
| `subdomain` | `checkin` | The page lives at `https://<subdomain>.<domain_name>`; set `""` to put it at `domain_name` itself |
| `aws_region` | `eu-central-1` | Region for everything, the certificate included |
| `event_timezone` | `Europe/Bratislava` | Your event's time zone, for "Already checked in at 09:14" |
| `name_prefix` | `cd-registration` | Prefix of every AWS resource name |
| `ssm_prefix` | `/cd-registration` | Where the settings live in SSM Parameter Store |
| `pretix_base_url` | `https://pretix.eu` | Change it only for your own pretix server |
| `project_tag` | `cd-registration-app` | Value of the `project` tag on every resource |

When it is done, `terraform -chdir=infrastructure output scanner_url` shows your page's address.

### 3.4 Tell AWS your pretix event

```bash
scripts/set-pretix-config.sh --organizer <slug> --list <check-in list ID>
```

### 3.5 Store the pretix token and choose the staff PIN

```bash
scripts/set-secrets.sh --token     # paste the token from 2.4; it is not shown
scripts/set-secrets.sh --pin       # type the PIN you want, twice (8+ letters or digits),
                                   # or press Enter for a random one, shown once
```

Both are stored encrypted in SSM, never in Terraform's state or in a file. The staff type the PIN once on their phones. A new PIN, or a new token, works within 5 minutes.

### 3.6 A key for the print PC

```bash
scripts/create-print-laptop-key.sh
```

It creates an access key for the print PC's own AWS user, which may only read and delete print requests. It prints **two short files**, shown only now: keep the window open for step 4.4.

### 3.7 The print PC's settings and package

```bash
cp app/print_laptop/.env.example app/print_laptop/.env
terraform -chdir=infrastructure output -raw print_queue_url     # copy this into QUEUE_URL
```

Edit `app/print_laptop/.env`:
- `TEMPLATE_PATH` and `TEMPLATE_2LINE_PATH`: where the sticker templates will be on the print PC (step 4.3), for example `C:\Users\<windows-user>\Desktop\attendee.lbx`;
- `QUEUE_URL`: the value just printed;
- `STICKER_ATTENDEE_TEXT` and `STICKER_YEAR_TEXT`: the sticker's second and third line, for example `Attendee` and `2027`;
- fonts and sizes, if you want others than the template's. Every key is explained in the file.

Then build the package for the print PC:

```bash
scripts/build-print-laptop-zip.sh       # writes dist/print-laptop.zip
```

The zip contains your `.env`, so `dist/` is git-ignored; copy the zip by USB stick or cloud drive, not by email.

---

## 4. The print PC (Windows)

### 4.1 Install, in this order

1. **The printer driver** for the QL-800/810W/820NWB, from Brother's support site for your model and Windows 11. Plug in the USB cable only when the installer asks.
2. **Windows printer settings** (Settings → Bluetooth & devices → Printers & scanners → Printer preferences): turn **off** "Windows protected print mode" and "Default install printers using Windows Ready Print", then restart.
3. In the printer's properties → **Ports**: "Enable bidirectional support" **on**, so the printer can report a problem such as an open cover.
4. **P-touch Editor**, Brother's label designer, from the same support page. Print one label from it: if that works, the printer is set up.
5. **Brother b-PAC, 64-bit**, from [Brother's b-PAC download page](https://support.brother.com/g/s/es/dev/en/bpac/download/index.html) (the Client Component is enough; the SDK includes it). Install one b-PAC package only.
6. **Python 3.14, 64-bit**, from [python.org](https://www.python.org/downloads/windows/). Check in PowerShell: `py -3.14 -c "import sys; print(sys.maxsize > 2**32)"` prints `True`.

On the printer, set **Auto Power Off** to **Off** (printer menu or Brother's Printer Setting Tool): a USB connection does not stop it from switching itself off mid-event.

### 4.2 Two sticker templates

The program fills a template you design in P-touch Editor. It finds the lines by their placeholder texts, so type them exactly as shown, whatever your real texts will be.

1. In P-touch Editor choose the printer **Brother QL-820NWB** and the loaded roll (File → Printer/Page Setup → Check Media), **Landscape**, and a fixed label length that fits your badges, for example 90 mm.
2. Add three text boxes, each centered and as wide as the sticker:
   - line 1: **Name Surname**
   - line 2: **Attendee**
   - line 3: **2027**
3. Save it as **`attendee.lbx`**, at the place `TEMPLATE_PATH` names.
4. For long names, make the two-line template: open `attendee.lbx`, save it as **`attendee-2line.lbx`**, change the first box's text to **Name**, add a box below it with the text **Surname**, keep the other two boxes, and save it where `TEMPLATE_2LINE_PATH` points. Names longer than 16 characters then print on two lines, each shrunk only as much as needed to fit.

Fonts can be set in the template or in `.env`; `.env` wins. A font must be installed on the print PC; Arial always is.

### 4.3 The program

1. Unzip `print-laptop.zip` into `C:\cd-registration\`. It creates `C:\cd-registration\print-laptop\`.
2. In PowerShell:
   ```powershell
   cd C:\cd-registration\print-laptop
   py -3.14 -m pip install --only-binary=:all: -r requirements.txt
   ```
3. Create the folder `C:\Users\<you>\.aws` and in it the two files that `create-print-laptop-key.sh` printed, `credentials` and `config`, **without a file extension**. In Notepad, choose "Save as type: All files", or it adds `.txt`. (With the AWS CLI installed, `aws configure --profile cd-print-laptop` writes both.)

### 4.4 Check and test print

```powershell
py -3.14 print_laptop.py --check
```

It lists everything the program depends on: Python, b-PAC, the printer and whether it is online, the loaded roll, both templates and the lines it found in them, and the fonts. Copy the loaded roll's name it shows (DK-22205 shows as `62mm`) into `ROLL` in `.env`: the program then refuses to print on a wrong roll.

```powershell
py -3.14 print_laptop.py --test
py -3.14 print_laptop.py --test "Maximilian Alexander Featherstonehaugh"
```

Each prints one sticker without AWS and says whether the printer confirmed it. The second shows a long name on the two-line template.

### 4.5 Start it

```powershell
py -3.14 print_laptop.py
```

It shows **"Print laptop ready: queue …"** and then one line per sticker: ✅ printed, ⏭ already printed, ❌ a problem with what to do. On the event day, double-click **`start-print-laptop.bat`** instead: it starts the program again whenever it stops.

---

## 5. Test the whole chain

1. **Admin computer → printer**, without pretix or a phone:
   ```bash
   scripts/send-test-print-request.sh "Your Name"
   ```
   A sticker prints. Running it again with the same ID prints nothing (`--id test-1`, twice): the print PC skips stickers it already printed.
2. **Phone → pretix → printer:** register a test attendee in your shop, and open the confirmation email's PDF on a screen. On a phone, open `https://checkin.<your domain>`, type the staff PIN, tap **Start**, allow the camera, and scan the QR code:
   - green card "Your Name — printing", and a sticker;
   - scan it again: amber card "Already checked in at …";
   - scan any other QR code: red card "Not valid".
3. **Optional, from the admin computer:** `scripts/scan-proof.sh <ticket secret>` runs five checks against the live API with one fresh test ticket: a wrong PIN, a scan, a repeated request (no second sticker), a second scan, and an unknown ticket. The ticket secret is the text inside its QR code; any QR reader app shows it.

---

## Scripts

All in `scripts/`, run on the admin computer from the repository root. Each one says what it does at the top of the file.

| Script | Use it to |
|---|---|
| `set-pretix-config.sh --organizer <slug> --list <id>` | Point AWS at your pretix organizer and check-in list |
| `set-secrets.sh --token` / `--pin` | Store the pretix token; choose or generate the staff PIN |
| `create-print-laptop-key.sh` | Make the print PC's AWS key |
| `delete-print-laptop-keys.sh` | Cut off a lost or stolen print PC key at once |
| `build-print-laptop-zip.sh` | Package the print PC's program with its `.env` |
| `send-test-print-request.sh [--id <id>] ["Name"]` | Print a test sticker through the queue |
| `scan-proof.sh <ticket secret>` | Check the scan API end to end with a test ticket |
| `queue-status.sh` | See how many print requests wait, and whether any failed |
| `redrive-dlq.sh` | Print again the requests that failed 5 times, after fixing the printer |
| `purge-print-queue.sh` | Throw away every waiting print request |
| `delete-secrets.sh` | Remove the token and the PIN after the event |
