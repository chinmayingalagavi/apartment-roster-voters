# Apartment voter matching

Match a voter list against apartment rosters and get one Excel workbook per apartment.

## Run from a terminal

Create a `data/` folder in this repository. Put the voter list and apartment rosters in it. Each file can be CSV or XLSX and can have any filename. Save the apartment list itself as `data/apartments.csv` or `data/apartments.xlsx`.

```csv
Bangalore South,Bangalore South constituency.xlsx
Sample Residency,Owners and tenants.xlsx
Example Heights,Example residents.csv
```

Put the AC or ward name in the first cell of row 1 and the voter filename in the second cell. Starting on row 2, put the full apartment name from the voter addresses in column A and its roster filename in column B. Use the first worksheet for XLSX files. Relative paths start at the folder containing the apartment list. [CSV template](code/apartments.example.csv)

Install Python 3.10 or newer. Open a terminal in this repository, then run the commands for your computer.

**Mac**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r code/requirements.txt
.venv/bin/python code/build_apartment_matches.py
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r code/requirements.txt
.\.venv\Scripts\python.exe code/build_apartment_matches.py
```

After setup, repeat just the last command. Open `output/` for the workbooks. The last column on each sheet, `searched_voter_list`, shows the AC or ward name.

The command uses `apartments.csv` first if both versions exist. To use a specific apartment list, add `--apartments-file` followed by its path. To choose a different voter file for one run, use `--voter-file` and give its AC or ward name with `--searched-voter-list`.

For new rosters, use one row per person with columns called `name` and `unit`. The four original roster formats are recognized by apartment name or by their usual `key` in an existing apartment list.

Put these column names on the first row of the voter file.

```csv
serial_number,epic_number,name,relation_type,relation_name,house_number,age,gender,section_raw,part,ward,corporation,pincode,pollingname,pollingaddress
```
