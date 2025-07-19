# DiFFDB

## Overview

**DiFFDB** is an open-source desktop tool for comparing the structure of relational databases across different environments (such as development, testing, and production) that share the same schema. The application quickly identifies differences between tables, views, synonyms, and sequences, generating detailed reports and SQL scripts to align environments.

The graphical interface, built with PyQt5, allows easy management of connection strings and intuitive navigation through the main features.

## Features

- **Connection Management**: Add, edit, and delete database connection strings via a user-friendly GUI.
- **Multi-Database Support**: Compatible with PostgreSQL, MySQL, SQLite, Oracle, and SQL Server (via SQLAlchemy).
- **Structural Comparison**: Analyze differences between two selected databases, including:
  - Missing tables or columns
  - Views, synonyms, and sequences present only in one environment
- **Reporting**:
  - Generate Excel reports (`differenze_ambienti.xlsx`) with all detected differences
  - Generate SQL scripts (`script_mancanti.sql`) to create or align missing objects
- **Modern Interface**: Dark theme, custom icons, window drag & drop, tab navigation
- **Error Handling**: Clear and localized error messages (Italian/English)

## Architecture

- **src/**: Main application logic (GUI, dialogs, DB comparison, utilities)
- **ui/**: Qt Designer `.ui` files for GUI layouts
- **styles/**: QSS stylesheet for dark theme
- **config/**: Configuration and SQL dialect templates
- **utils/**: Support modules (DB connection, error handling, DDL parsing)
- **classes/**: Configuration class definitions

## Main Components

- [`src/main_window.py`](src/main_window.py): Main window, tab management, UI loading, comparison and connection logic
- [`src/dialogs.py`](src/dialogs.py): Dialogs for adding/editing connections
- [`src/diff_DB.py`](src/diff_DB.py): Functions for environment comparison, SQL script and Excel report generation
- [`utils/databaseConnector.py`](utils/databaseConnector.py): Database connection management via SQLAlchemy
- [`utils/errorMessages.py`](utils/errorMessages.py): Centralized error message handling
- [`config/dialectConfig.py`](config/dialectConfig.py): SQL templates for supported databases

## Supported Databases

- PostgreSQL
- MySQL
- SQLite
- Oracle
- SQL Server

## How It Works

1. **Configure Connections**: Use the "Configuration" tab to add, edit, or delete database connection strings.
2. **Select Environments**: In the "Selection" tab, choose the two databases to compare.
3. **Compare**: Click the "Compare" button to analyze structural differences between the two environments.
4. **Output**:
   - An Excel file is generated with detailed differences.
   - An SQL script is generated to align missing objects.

## Installation

### Prerequisites

- Python 3.8+
- [pip](https://pip.pypa.io/en/stable/)

### Dependencies

All dependencies are listed in [requirements.txt](requirements.txt). Install them with:

```sh
pip install -r [requirements.txt](http://_vscodecontentref_/0)