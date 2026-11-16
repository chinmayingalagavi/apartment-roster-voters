# Apartment voter matching

Run this Python script to match apartment rosters against a voter list and get one Excel workbook per apartment.

## 1. Add your files

Install Python 3.10 or newer. Open a terminal in the repository folder, the one containing `code/`. Create a `data/` folder and put these files inside it. The input files are supplied separately from the repository.

- **Constituency voter list** saved as `ac_voters.csv`. Use a prepared CSV with the header shown below.
- **One roster per apartment** in Excel (`.xlsx`) or CSV. For a new apartment, use one row per person, with a `name` column and a `unit` column such as `B102`. You can also use `block` and `unit_part` instead of `unit`. The `status` column is optional.
- **Apartment list** saved as `apartments.csv`. Use [the example](code/apartments.example.csv) as a template, with one row per apartment.

```csv
key,apartment_name,roster_path
sample_residency,Sample Residency,sample_residency.xlsx
```

Use a unique short `key`, the full apartment name as it appears in voter addresses, and the roster filename. The script reads this list automatically. For the four original roster formats, use their existing keys `concorde`, `purnima`, `silicon_oasis`, and `tirumala_vintage`.

The voter CSV needs these columns.

```csv
serial_number,epic_number,name,relation_type,relation_name,house_number,age,gender,section_raw,part,ward,corporation,pincode,pollingname,pollingaddress
```

## 2. Install and run

On **Mac**, run these commands from the repository folder.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r code/requirements.txt
.venv/bin/python code/build_apartment_matches.py --voter-csv data/ac_voters.csv --output-dir output/ac
```

On **Windows**, use PowerShell.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r code/requirements.txt
.\.venv\Scripts\python.exe code/build_apartment_matches.py --voter-csv data/ac_voters.csv --output-dir output/ac
```

Run just the last command after the first setup. To run one apartment, put its key after `build_apartment_matches.py`. To use the ward list, save it as `data/voters.csv` and omit both flags.

## 3. Open the results

Look in `output/ac/` for one workbook per apartment, for example `sample_residency_voters.xlsx`. A ward run writes to `output/`.

- `voters_mapped_tohouse` lists voters linked to flats with a roster status assigned.
- `voters_unmapped` lists households whose address names the apartment without a matched flat, plus voters with a known flat and unassigned roster status.
- `not_found_in_voterlist` lists roster entries with no voter link to that person at their flat.
