<!-- Copyright (c) 2026-2027 Michal Salanci. SPDX-License-Identifier: MIT -->

# Community Day check-in

Check-in with name stickers for a one-day community event that sells (or gives away) its tickets in [pretix](https://pretix.eu).

At the entrance, volunteers scan each attendee's ticket QR code with their phone. The ticket is checked in at pretix, and a Brother label printer next to the desk prints a sticker with the attendee's name, which goes on their badge. Scanning the same ticket again shows "Already checked in at 09:14"; a cancelled or fake ticket shows "Not valid".

```
 Phone (browser)                AWS (your account)                       pretix
 ┌──────────────┐  HTTPS   ┌──────────────────────────┐   check in   ┌────────────┐
 │ scanner page │ ───────► │ API Gateway + Lambda     │ ───────────► │ your event │
 └──────────────┘          │ at checkin.<your domain> │              └────────────┘
                           └────────────┬─────────────┘
                                        │ print request (name only)
                                        ▼
                           ┌──────────────────────────┐
                           │ SQS queue                │
                           └──────────────────────────┘
                                        ▲
                                        │ pulls (HTTPS)
 At the desk               ┌────────────┴─────────────┐   USB   ┌───────────────────┐
                           │ Windows computer         │ ──────► │ Brother QL-820NWB │
                           │ with the print program   │         │ label printer     │
                           └──────────────────────────┘         └───────────────────┘
```

AWS keeps no attendee database: pretix holds the registrations, and a name exists in AWS only while its print request waits in the queue. Normally that is a few seconds. If the print computer is off or its prints fail, a request waits up to 1 day in the queue, and one that failed 5 times waits in a second queue (the dead-letter queue) until it is 2 days old. The logs keep order codes, never names, for 7 days. The cost is a few cents for the day, plus the domain.

There are three places you work in:
- **pretix**, in the browser: the event, its check-in list and an API token;
- **the admin computer** (macOS or Linux): deploys everything to AWS and stores the settings;
- **the print computer** (Windows): runs the program that prints the stickers.

In this guide, **`example.org` stands for your domain**; put your own wherever it appears.

---

# 1. What you need

## 1.1 Pretix, AWS, Domain
| What | Notes |
|---|---|
| **pretix** organizer account | [pretix.eu](https://pretix.eu) (hosted) or your own pretix server. On pretix.eu a new organizer account is reviewed by hand before a shop can go live: **start this first**, it is the slowest step. Turn on two-factor authentication. |
| **AWS account** | With an admin user or role you can use from the AWS CLI. Everything runs in this one account. |
| **A domain** | Any domain you control, with its DNS at any provider. The scanner page gets its own address, `checkin.example.org`. Terraform writes the page's DNS records into a public Route 53 hosted zone in this AWS account: either your domain's own zone, if it is already in Route 53 here, or a small zone just for `checkin.example.org`, which you hand over from your DNS provider with one NS record (below). Terraform only adds records; it never changes the zone itself. |

**If your domain's DNS is not in Route 53 in this account** (another DNS provider, or Route 53 in another AWS account), hand just the page's own name, `checkin.example.org`, over to this account. Your domain stays where it is:

1. In this AWS account, create a public hosted zone for that name:
   ```bash
   aws route53 create-hosted-zone --name checkin.example.org --caller-reference "$(date +%s)"
   ```
   The answer lists the zone's four name servers (`DelegationSet.NameServers`). Run it **once**: each run makes another zone. If you ran it twice, delete the extra zone and keep the one whose name servers are in the NS record of step 2.
2. At your DNS provider, in the zone `example.org`, add an **NS** record named `checkin` with those four name servers. If `example.org` is in Route 53 in another AWS account, the NS record goes into that account's hosted zone for `example.org`.
3. Check that it works (it can take a few minutes): `dig NS checkin.example.org +short` shows the four AWS name servers.
4. In step 3.3 set `domain_name = "checkin.example.org"` and `subdomain = ""`. The page is then `https://checkin.example.org`.

The zone costs $0.50 a month. If you ever delete it, remove the NS record at your DNS provider first, or someone else could claim the name.

## 1.2 The Computer(s)
**Two computers, or one.** The **admin computer** (macOS or Linux) deploys the system to AWS and runs the scripts. The **print computer** (Windows) sits at the desk and prints the stickers; the check-ins themselves happen on the staff's phones. They are two because the print program uses Brother's b-PAC SDK, which exists only for Windows, while the admin scripts are written for bash. One Windows computer could do both, running the admin part in WSL (Linux on Windows), but that has not been tested.

### The admin computer (macOS or Linux)

| Tool | Version | Check with |
|---|---|---|
| Terraform | 1.17 or a later 1.x | `terraform version` |
| AWS CLI | v2, with credentials for your account | `aws sts get-caller-identity` |
| Python | 3.10 or later (the scripts use it for small JSON jobs) | `python3 --version` |
| bash, curl, uuidgen, zip, unzip, git | any recent | already on macOS; on Debian or Ubuntu, `zip` and `uuidgen` (package `uuid-runtime`) may need installing |
| dig | any | only for the DNS check above; on Debian or Ubuntu it is in the `dnsutils` package |

On Debian or Ubuntu, `sudo apt install zip uuid-runtime dnsutils` installs the missing ones.

The scripts and Terraform use the AWS CLI's **default** credentials. To use another profile, run `export AWS_PROFILE=<name>` in that terminal first. The scripts use the app's region (`aws_region` from 3.3) on their own.

### The print computer

**Hardware**

| What | Notes |
|---|---|
| A computer with **Windows 11, x64** | Tested on Windows 11. Not Windows on ARM: Brother has no drivers for it. You need admin rights for the installs, a free USB port, and **internet access** (Wi-Fi or cable): the computer fetches print requests from AWS. |
| **Brother QL-820NWB** label printer with its USB cable | The only printer tested. It is connected by **USB**: over Wi-Fi or a network cable, Brother says not every printer error is reported. |
| A label roll, for example **DK-22205** (62 mm continuous paper) | The roll's 62 mm are the sticker's width; you choose its length (the templates use 40 mm). Pick a length that fits the blank space on your badges. |

**Software**, all free, installed in step 4.1 in this order:

| Software | Version | Where to get it | What it is for |
|---|---|---|---|
| **Printer driver** for QL-800/810W/820NWB | **1.10.1c** or later | [Brother support, QL-820NWB downloads](https://support.brother.com/g/b/downloadtop.aspx?c=gb&lang=en&prod=lpql820nwbeuk) (choose your country and Windows 11) | Lets Windows print to the printer |
| **P-touch Editor** | **6** (tested with 6.13) | the same Brother downloads page | A first test print (step 4.1); changing the sticker templates, only for another roll (step 4.2) |
| **Printer Setting Tool** | the current one | the same Brother downloads page | Turning off the printer's Auto Power Off |
| **b-PAC Client Component, 64-bit** | **3.4.017** | [Brother b-PAC downloads](https://support.brother.com/g/s/es/dev/en/bpac/download/index.html): "b-PAC Client Component Only", 64-bit (`.msi`). The 64-bit "Full b-PAC SDK" also works; it includes the same component. | Lets the print program fill a template and print it. Install **one** b-PAC package, and the **64-bit** one: it must match 64-bit Python. |
| **Python, 64-bit** | **3.14** | [python.org, Windows downloads](https://www.python.org/downloads/windows/): "Windows installer (64-bit)" | Runs the print program |
| Python packages `pywin32` and `boto3` | as pinned in `requirements.txt` | installed by one `pip` command in step 4.3 | b-PAC access from Python; reading the AWS queue |

The AWS CLI is **not** needed on the print computer: its AWS key goes into two small text files (step 4.3).

### Phone(s)

Any phone with a camera and internet access (mobile data or the venue's Wi-Fi): an **Android phone with Chrome** (tested), or an **iPhone with Safari** (iOS 16 or later; not tested yet). Open the page in the browser itself, from a bookmark or by typing the address, not from inside a chat app: their built-in browsers often have no camera access.

---

# 2. Setting up

## 2.1 Create the pretix event

Create the event as a **single event**: leave "This is an event series" unchecked. pretix asks only once, in the creation wizard, and it cannot be changed later.

Then set:

| Setting | Where | Value | Why |
|---|---|---|---|
| Attendee names | Settings → General, section "Customer and attendee data" → Attendee data | Asked **and required** for every ticket | The name on the sticker comes from the ticket |
| Name format | the same section → Form settings | **Given name, family name** | The sticker prints them as one or two lines |
| Email | the same section | Nothing to set: pretix always asks for it | pretix sends the ticket by email |
| Maximum number of items per order | Settings → General, section "Cart" | **1** | One name per order keeps it simple |
| Product | Products | For example one free product, "Attendee", without approval | |
| "Ask for invoice address" | Settings → Invoicing | **Off** | Checkout then asks only for the email and the name |

Leave the ticket code generator at its default (random), and **never change it after registration opens**, or QR codes already sent may stop working.

## 2.2 Make sure the email carries the QR code

The QR code is only in the **PDF ticket attached** to the confirmation email, never in the email's text. That needs four settings:

1. Settings → Tickets → **"Allow users to download tickets"**: on (off by default).
2. On the same page, the **PDF** ticket output: enabled.
3. On the same page, **"Download date"**: empty.
4. Settings → E-mail → **"Attach ticket files"**: on.

Check with one test registration (see **Testing** at the end of 2.3): the confirmation email has a PDF with a QR code.

## 2.3 The check-in list

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

## 2.4 An API token

The AWS side calls pretix with an API token:

1. Open `https://pretix.eu/control/organizer/<slug>/teams` (your organizer → Teams).
2. Click the team the token should belong to. A team with access to your event and permission to check in is enough. A team with full rights works too, but then the token can do anything in your organizer account.
3. Scroll down to **API tokens**, type a name such as `lambda`, and click the button next to it.
4. pretix shows the token **once**. Keep it at hand for step 3.5; it goes straight into AWS and nowhere else.

---

# 3. The admin computer: deploy and configure

All commands below run from the root of this repository, unless they `cd` somewhere.

## 3.1 Get the code and check AWS

```bash
git clone https://github.com/msalanci/aws-communityday-checkin.git
cd aws-communityday-checkin
aws sts get-caller-identity        # shows the account you will deploy to
```

**Your settings go into five files you make yourself.** The repository holds no file with anyone's settings. Next to each settings file there is an **example** with the same name plus `.example`. For each one you **copy** the example to the name **without `.example`**, and put your values into the copy. Keep the `.example` file as it is: git tracks it, while your copy is git-ignored, so your settings never end up in git or on GitHub.

| The example, in the repository | Your copy: the same name without `.example` | Filled in at | What goes in | Format |
|---|---|---|---|---|
| `infrastructure/bootstrap/terraform.tfvars.example` | `infrastructure/bootstrap/terraform.tfvars` | step 3.2 | the state bucket's name | `name = "value"`: text in quotes, `true`/`false` without |
| `infrastructure/bootstrap/backend.hcl.example` | `infrastructure/bootstrap/backend.hcl` | step 3.2 | where the bootstrap's state file lives | `name = "value"`: text in quotes, `true`/`false` without |
| `infrastructure/terraform.tfvars.example` | `infrastructure/terraform.tfvars` | step 3.3 | your domain and the app's other settings | `name = "value"`: text in quotes, `true`/`false` without |
| `infrastructure/backend.hcl.example` | `infrastructure/backend.hcl` | step 3.3 | the state bucket and its region | `name = "value"`: text in quotes, `true`/`false` without |
| `app/print_laptop/.env.example` | `app/print_laptop/.env` | step 3.7 | the print computer's settings | `NAME=value`, no quotes |

Each step below shows its own copy commands, for example:

```bash
cp infrastructure/bootstrap/terraform.tfvars.example infrastructure/bootstrap/terraform.tfvars
```

- **Copy in the terminal, don't rename the file in Finder or Explorer.** Renaming removes the example, and Finder hides names that start with a dot, such as `.env` (Cmd+Shift+. shows them).
- **Edit the copy** with any text editor, for example `nano infrastructure/bootstrap/terraform.tfvars` or VS Code. Lines starting with `#` are explanations; leave them or delete them.
- **Check:** `git status` never lists your copies. If one shows up, its name is wrong (it must end exactly as in the table above).

## 3.2 The state bucket (once)

Terraform keeps its state in an S3 bucket. A small separate configuration, the bootstrap, creates that bucket. Its own state is a local file, which you keep **outside** this repository and back up: without it, Terraform no longer knows the bucket.

```bash
mkdir -p ~/checkin-private/bootstrap                     # any folder outside the repository
cd infrastructure/bootstrap
cp terraform.tfvars.example terraform.tfvars             # your copy; the .example stays
cp backend.hcl.example backend.hcl                       # your copy; the .example stays
```

Edit the two copies, not the `.example` files:
- `terraform.tfvars`: `state_bucket_name`, a name no one in the world uses yet, for example `example-org-checkin-tf-state`;
- `backend.hcl`: `path`, the state file in the folder you just made, for example `path = "/Users/<you>/checkin-private/bootstrap/terraform.tfstate"` on macOS or `path = "/home/<you>/checkin-private/bootstrap/terraform.tfstate"` on Linux.

The bucket is created in `eu-central-1`. For another region, add the line `aws_region = "<region>"` to this `terraform.tfvars`. The bootstrap has its own `aws_region` and `project_tag`, separate from the app's in 3.3.

```bash
terraform init -backend-config=backend.hcl
terraform apply                                          # type yes
cd ../..
```

The bucket is versioned, encrypted, private and protected from `terraform destroy`; keep it for next year.

## 3.3 The app (certificate, API, Lambdas, queue)

```bash
cd infrastructure
cp terraform.tfvars.example terraform.tfvars             # your copy; the .example stays
cp backend.hcl.example backend.hcl                       # your copy; the .example stays
```

Edit the two copies, not the `.example` files:
- `terraform.tfvars`: `domain_name`, and anything else from the table below;
- `backend.hcl`: `bucket`, the bucket from 3.2, and `region`, the bucket's region from 3.2 (the app's own `aws_region` in `terraform.tfvars` may be another one). Leave `key`, `encrypt` and `use_lockfile` as they are; `true` has no quotes.

```bash
terraform init -backend-config=backend.hcl
terraform plan
terraform apply                                          # type yes; the certificate takes a few minutes
cd ..
```

| Variable | Default | Meaning |
|---|---|---|
| `domain_name` | — (required) | Your Route 53 zone: `example.org`, or `checkin.example.org` for a zone made just for the page. In lowercase, without a dot at the end |
| `subdomain` | `checkin` | The page lives at `https://<subdomain>.<domain_name>`. One word without dots: lowercase letters, digits and hyphens. Set `""` to put the page at `domain_name` itself, only with a zone made just for the page (1.1). The page's name must not already have a record in the zone |
| `aws_region` | `eu-central-1` | Region for everything, the certificate included |
| `event_timezone` | `Europe/Bratislava` | Your event's time zone, for "Already checked in at 09:14". Set it unless the event is in Central European time, with an IANA name such as `Europe/London` |
| `name_prefix` | `cd-registration` | Prefix of every AWS resource name |
| `ssm_prefix` | `/cd-registration` | Where the settings live in SSM Parameter Store |
| `pretix_base_url` | `https://pretix.eu` | Change it only for your own pretix server: `https://` and the server's name, with no path and no `/` at the end |
| `project_tag` | `cd-registration-app` | Value of the `project` tag on every resource |

When it is done, `terraform -chdir=infrastructure output scanner_url` shows your page's address.

## 3.4 Tell AWS your pretix event

```bash
scripts/set-pretix-config.sh --organizer <slug> --list <check-in list ID>
```

Give both the first time; later you can give either one alone, to change only that one. The slug is lowercase letters, digits and hyphens, for example `my-community`; the list ID is digits only, for example `123456`. The Lambda uses a new value within 5 minutes.

## 3.5 Store the pretix token and choose the staff PIN

```bash
scripts/set-secrets.sh --token     # paste the token from 2.4; it is not shown
scripts/set-secrets.sh --pin       # type the PIN you want, twice, or press Enter for a random one
```

The PIN: at least 8 characters, and only the letters A–Z and a–z and the digits 0–9 (no accents, spaces or symbols). Enter alone makes a random PIN of 10 characters and shows it once: write it down.

Both are stored encrypted in SSM, never in Terraform's state, and not kept in any file. A new PIN, or a new token, works within 5 minutes.

**The PIN on the phones.** The staff type the PIN once on each phone; it stays there until someone taps **Change PIN**. **Start** accepts any PIN: a wrong one shows at the first scan, as the PIN screen with "Wrong PIN". That ticket was **not** checked in, so type the right PIN and scan it again. After a new PIN (`scripts/set-secrets.sh --pin`), every phone shows "Wrong PIN" at its next scan, and the staff type the new one. If a phone with the PIN is lost, set a new PIN.

## 3.6 A key for the print computer

```bash
scripts/create-print-laptop-key.sh
```

It creates an access key for the print computer's own AWS user, which may only read and delete print requests. It prints **two short files**, shown only now. You need them in step 4.3, much later: save their text somewhere safe until then, such as a password manager, or run this step just before 4.3.

The script refuses while the user already has a key. If you lost the output, run `scripts/delete-print-laptop-keys.sh` (type `delete` when it asks), then this script again.

## 3.7 Preparation of settings and package necessary for the print computer

On Admin computer:
```bash
cp app/print_laptop/.env.example app/print_laptop/.env          # your copy; the .example stays
terraform -chdir=infrastructure output -raw print_queue_url     # copy this into QUEUE_URL
```

Edit the copy, `app/print_laptop/.env` (not `.env.example`), for example with `nano app/print_laptop/.env`. Every key is explained in the file; these you check or change:

| Key | Set it to |
|---|---|
| `TEMPLATE_PATH`, `TEMPLATE_2LINE_PATH` | Where the two sticker templates will be on the print computer: its Desktop (you copy them there in step 4.2). Replace `<windows-user>` with your Windows user name: `C:\Users\<windows-user>\Desktop\attendee.lbx` and `C:\Users\<windows-user>\Desktop\attendee-2line.lbx`. No quotes needed. The user name is the last part of what `echo $env:USERPROFILE` shows in PowerShell on the print computer. If its Desktop is in OneDrive, the Desktop is in another folder, for example `C:\Users\<windows-user>\OneDrive\Desktop`: these paths, and the `cd` commands in section 4, must point to where the Desktop really is. |
| `PRINTER_NAME` | The printer's name **exactly as Windows shows it** in Settings → Bluetooth & devices → Printers & scanners. The driver names it `Brother QL-820NWB`. |
| `ROLL` | `62mm` for DK-22205. For another roll, `--check` shows its name in step 4.4. The value must equal the loaded roll's name exactly, without the quotes `--check` puts around it. Empty: the program compares the loaded roll with the roll each template is made for instead. While no roll is loaded, or the roll does not match, the program prints no stickers and shows ❌ with the reason. |
| `STICKER_ATTENDEE_TEXT`, `STICKER_YEAR_TEXT` | The sticker's second and third line, for example `Attendee` and `2027` |
| `STICKER_…_FONT`, `_SIZE`, `_BOLD` | Fonts and sizes, if you want others than the template's |
| `AWS_PROFILE`, `AWS_REGION` | Leave `cd-print-laptop` (the name in the files from 3.6) and your region from 3.3 |
| `QUEUE_URL` | The value just printed |

Then build the package for the print computer:

```bash
scripts/build-print-laptop-zip.sh       # writes dist/print-laptop.zip
```

The zip contains your `.env`, so `dist/` is git-ignored; copy the zip by USB stick or cloud drive, not by email. Later changes to a setting can be made in the `.env` on the print computer itself, next to `print_laptop.py`, with Notepad. The program reads `.env` only when it starts, so restart it after a change. A new zip unzipped over the folder replaces that `.env`, so make the same change in `app/print_laptop/.env` on the admin computer too.

---

# 4. The print computer (Windows)

## 4.1 Install, in this order

1. **The printer driver** (see the software table in section 1.2). Run the installer and **plug in the USB cable only when it asks**.
2. **Windows printer settings:** Settings → Bluetooth & devices → Printers & scanners → Printer preferences: turn **off** "Windows protected print mode" and "Default install printers using Windows Ready Print", then restart Windows. With either one on, Brother's software may not see the printer.
3. **Bidirectional support:** in Printers & scanners, open the Brother QL-820NWB → Printer properties → **Ports** tab: tick "Enable bidirectional support", so the printer can report a problem such as an open cover.
4. **P-touch Editor 6.** Print one label from it: if that works, the printer and driver are set up.
5. **Printer Setting Tool:** open it, choose the QL-820NWB, and set **Auto Power Off** to **Off** (you can also do this in the printer's own menu). A USB connection does not stop the printer from switching itself off in the middle of the event.
6. **b-PAC Client Component 3.4.017, 64-bit.** Only this one b-PAC package.
7. **Python 3.14, 64-bit.** In the installer, keep "py launcher" ticked. Then check in PowerShell:
   ```powershell
   py -3.14 -c "import sys; print(sys.maxsize > 2**32)"
   ```
   It must print `True`. `False` means a 32-bit Python, which cannot use the 64-bit b-PAC.

## 4.2 The sticker templates

You do not have to make them: the repository has both, in `app/print_laptop/templates/`. Copy them to the print computer (on the same USB stick as the zip, for example) and put them on its **Desktop**:

| Copy this file from the repository | to the print computer as | `.env` key that points at it |
|---|---|---|
| `app/print_laptop/templates/attendee.lbx` | `C:\Users\<you>\Desktop\attendee.lbx` | `TEMPLATE_PATH` |
| `app/print_laptop/templates/attendee-2line.lbx` | `C:\Users\<you>\Desktop\attendee-2line.lbx` | `TEMPLATE_2LINE_PATH` |

`<you>` is your Windows user name: the same one you put into those two keys in step 3.7, the last part of what `echo $env:USERPROFILE` shows in PowerShell. `attendee.lbx` prints names up to 16 characters (`STICKER_NAME_FIT_CHARS`) on one line; the 16 include the space between first and last name. `attendee-2line.lbx` prints longer names on two lines, first name and last name, each shrunk only as much as needed. A long name that is a single word stays on one line, smaller. With `TEMPLATE_2LINE_PATH` empty, every long name stays on one line, smaller.

They are made for the **DK-22205** roll (62 mm continuous paper) and a **62 × 40 mm** label, in Arial. With that roll there is nothing more to do.

**Another roll or another label length:** open a template from the Desktop in P-touch Editor, choose your roll (File → Printer/Page Setup → Check Media) and your length, and save it: under the same name, or under a new name and then point `TEMPLATE_PATH` (or `TEMPLATE_2LINE_PATH`) in `.env` at it. Do the same with the other one. Keep their text boxes and placeholder texts as they are (`Name Surname`, `attendee`, `2027`; in the two-line one `Name`, `Surname`, `attendee`, `2027`): the program finds each line by that text and puts the real one in. Then set `ROLL` in `.env` to the loaded roll's name as `--check` shows it (step 4.4). A new zip never touches the templates on the Desktop.

Fonts can be set in the template or in `.env`; `.env` wins. A font must be installed on the print computer; Arial always is.

### 4.3 The program and its AWS key

1. Unzip `print-laptop.zip` onto the **Desktop**, next to the two templates. The zip already holds the folder `print-laptop`, so extract it into the Desktop itself: choose `C:\Users\<you>\Desktop` as the destination. The result is `C:\Users\<you>\Desktop\print-laptop\print_laptop.py`. If you get `print-laptop\print-laptop\` instead, move the inner folder onto the Desktop.
2. In PowerShell:
   ```powershell
   cd $env:USERPROFILE\Desktop\print-laptop
   py -3.14 -m pip install --only-binary=:all: -r requirements.txt
   ```
3. Put the AWS key on the computer: make the folder, then open Notepad there:
   ```powershell
   mkdir $env:USERPROFILE\.aws
   notepad
   ```
   Paste the first file that `create-print-laptop-key.sh` printed (it starts with `[cd-print-laptop]`) and save it in `C:\Users\<you>\.aws` as **`credentials`**: choose "Save as type: **All files**", or Notepad adds `.txt`. Do the same with the second file (it starts with `[profile cd-print-laptop]`), saved as **`config`**.

### 4.4 Check and test print

```powershell
cd $env:USERPROFILE\Desktop\print-laptop
py -3.14 print_laptop.py --check
```

It needs no AWS and prints nothing. It lists everything the program depends on: Python, b-PAC, the printer and whether it is online, the loaded roll, both templates and the lines it found in them, and the fonts. If the loaded roll's name it shows differs from `ROLL` in `.env`, put it there, without the quotes around it.

The list must show **"Print confirmation: b-PAC's Printed event"**. Without it, the program does not start its queue loop, even if `--test` prints.

If something essential is missing, `--check` stops with a single ❌ line instead (exit code 2): the `.env` cannot be loaded (a missing or wrong setting, named in the line), Python is 32-bit, pywin32 or b-PAC cannot start, or `PRINTER_NAME` is not installed (the line lists the installed printers' names, so you can copy the right one).

```powershell
py -3.14 print_laptop.py --test
py -3.14 print_laptop.py --test "Maximilian Alexander Featherstonehaugh"
```

Each prints one sticker without AWS and says whether the printer confirmed it. The second shows a long name on the two-line template.

### 4.5 Start it

```powershell
cd $env:USERPROFILE\Desktop\print-laptop
py -3.14 print_laptop.py
```

It shows **"Print laptop ready: queue …"** and then one line per sticker: ✅ printed, ⏭ already printed, ❌ a problem with what to do. Other lines are ⚠️ a warning and ℹ️ information.

Stop it with Ctrl+C. The first Ctrl+C shows "Stopping after the current step (Ctrl+C again stops at once)"; after a failed print, that step can take up to about two minutes. A second Ctrl+C stops it at once.

On the event day, double-click **`start-print-laptop.bat`** in the `print-laptop` folder on the Desktop instead: it starts the program again 5 seconds after it stops, for any reason, Ctrl+C included. To stop it, close its window. Only one copy of the program can run at a time; a second one shows ❌ "Another copy of the print laptop program is already running; close the other window". So close the PowerShell window from this step before you start the `.bat`.

**If it cannot reach AWS:** "❌ No connection to AWS — retrying" or "❌ Cannot use the AWS profile …" means: check the internet connection, the two files in `C:\Users\<you>\.aws` (step 4.3), and `QUEUE_URL` in `.env`. The profile message says "Run: aws configure --profile cd-print-laptop", but the AWS CLI is not needed: the two files you made by hand in step 4.3 do the same.

---

## 5. Test the whole chain

1. **Admin computer → printer**, without pretix or a phone:
   ```bash
   scripts/send-test-print-request.sh "Your Name"
   ```
   A sticker prints. Run `scripts/send-test-print-request.sh --id test-1 "Your Name"` twice: the second time nothing prints and the print computer shows ⏭, because it skips stickers it already printed. The print computer remembers printed IDs for 48 hours, so to repeat this test within two days, use another ID, such as `test-2`. Keep `printed_ids.txt` in the program folder during the event: it is what stops a repeated request from printing twice.
2. **Phone → pretix → printer:** register a test attendee in your shop, and open the confirmation email's PDF on a screen. On a phone, open `https://checkin.example.org` (`terraform -chdir=infrastructure output scanner_url` shows the address), type the staff PIN, tap **Start**, allow the camera, and scan the QR code:
   - green card "Your Name — printing", and a sticker;
   - wait 10 seconds, then scan it again: amber card "Already checked in at …". The page ignores the same ticket for 10 seconds after its answer, and every ticket for 2 seconds;
   - scan any other QR code: red card "Not valid".
3. **Search and Reprint:** register one more test attendee from a phone, open the **Search** tab and type part of the name: the attendee is listed without ✓. Tap the row: green card and a sticker, and the row now shows ✓. Tap the row again: green "Reprinting …" and a second sticker; pretix still shows one check-in. Search for that attendee's email: nothing is found.
4. **Optional, from the admin computer:** `scripts/scan-proof.sh <ticket secret>` runs five checks against the live API with one fresh test ticket: a wrong PIN, a scan, a repeated request (no second sticker), a second scan, and an unknown ticket. The ticket secret is the text inside its QR code; any QR reader app shows it. The script first asks you to type `yes`, then the staff PIN (not shown). It really checks the ticket in on the live check-in list, so use a test registration only. It prints each answer under a label that says what to expect ("expect …"); it does not judge pass or fail, so compare them yourself. Keep the print computer running, so that it shows ⏭ for check 3.

**What the cards mean**

| Card on the phone | What it means |
|---|---|
| green "Your Name — printing" | Checked in. The sticker is in the print queue; it is not printed yet. |
| green "Reprinting Your Name" | Reprint worked: another sticker is in the print queue. The ticket was not checked in again. |
| amber "Already checked in at 09:14" (or without a time) | The ticket was checked in before. No sticker prints. Tap **Reprint** if the attendee needs another one. |
| amber "Checked in, but the sticker wasn't sent — tap Reprint" | Checked in, but its print request did not reach the queue. Tap **Reprint**. |
| amber "The sticker wasn't sent — tap Reprint again" | A reprint did not reach the queue. Tap **Reprint** again. |
| amber "Not checked in yet — scan the ticket instead" | Reprint was asked for a ticket that is not checked in. Scan it, or tap it in the search. |
| red "Not valid — please write your name on your badge" | Refused: pretix does not accept the ticket (for example cancelled, unknown or fake), or the QR code holds more than 200 characters. Also a ticket without a name: pretix has checked that one in, but there is no name to print. |
| grey, with **Try again**: "No answer — try again", "Too many scans at once — try again", "pretix did not answer — try again", "pretix is busy — try again in a few seconds", "Something was wrong with the request — try again" or "Something went wrong — try again" | A technical failure. Tap **Try again**: it sends the same request again, with the same nonce, so it never checks a ticket in or prints a sticker twice. |
| grey "The system can't use pretix — call the organizer" | A setting is missing or wrong (redo 3.4 and 3.5), or pretix refused the token, the organizer or the check-in list. |

Green, amber and red each have their own beeps and vibration; grey has none. iPhones do not vibrate from web pages.

**Search and Reprint.** The **Search** tab finds an attendee whose QR code cannot be scanned: type at least 3 letters of the name or the order code (not the email). Accents and capitals do not matter, so `novak` finds "Novák". Each row shows the name, the order code and "✓ 09:14" once checked in. Tap a row without ✓ to check that attendee in (a sticker prints); tap a row with ✓ to print another sticker. **Reprint** on an amber card does the same for the ticket just scanned. A reprint never checks a ticket in again, and tapping it once prints one sticker. The camera rests while the Search tab is open.

**After the event**, on the admin computer, in this order:
1. `scripts/delete-secrets.sh` (type `delete`): removes the pretix token and the staff PIN; within 5 minutes the page stops working. Run it first: it reads Terraform's outputs, which `destroy` removes.
2. `terraform -chdir=infrastructure destroy` (type `yes`): removes everything step 3.3 created, the print computer's AWS user and its key included.
3. The state bucket from 3.2 stays: it is protected from `destroy`. Keep it for next year.
4. If you made a zone just for the page (1.1), it stays too, because Terraform did not create it. Before you ever delete it, remove its NS record at your DNS provider.

---

## Scripts

All in `scripts/`, run on the admin computer from the repository root. Each one says what it does at the top of the file. Type each one as `scripts/<name>`, for example `scripts/queue-status.sh`: the bare name alone does not run. By its full path, a script also works from any other folder.

Every script except `build-print-laptop-zip.sh` reads its AWS names from `terraform output` of `infrastructure/`, so it works only on a computer where step 3.3 (`terraform init` and `terraform apply`) was done. Some scripts ask you to type a word before they act (shown in the table); anything else ends with "Error: cancelled" and changes nothing.

| Script | Use it to |
|---|---|
| `set-pretix-config.sh [--organizer <slug>] [--list <id>]` | Point AWS at your pretix organizer and check-in list; give either or both. The slug is lowercase letters, digits and hyphens; the list ID is digits only |
| `set-secrets.sh --token` / `--pin` | Store the pretix token; choose or generate the staff PIN |
| `create-print-laptop-key.sh` | Make the print computer's AWS key |
| `delete-print-laptop-keys.sh` | Cut off a lost or stolen print computer key at once (asks you to type `delete`) |
| `build-print-laptop-zip.sh` | Package the print computer's program with its `.env` |
| `send-test-print-request.sh [--id <id>] ["Name"]` | Print a test sticker through the queue |
| `scan-proof.sh <ticket secret>` | Check the scan API end to end with a test ticket (asks you to type `yes`) |
| `queue-status.sh` | See how many print requests wait, and whether any failed |
| `redrive-dlq.sh` | Print again the requests that failed 5 times, after fixing the printer |
| `purge-print-queue.sh` | Throw away every waiting print request (asks you to type `purge`) |
| `delete-secrets.sh` | Remove the token and the PIN after the event (asks you to type `delete`) |

---

**Licence:** MIT, see `LICENSE`. `app/lambda/web/static/vendor/html5-qrcode.min.js` is html5-qrcode, under the Apache License 2.0: see `app/lambda/web/static/vendor/html5-qrcode.LICENSE`.
