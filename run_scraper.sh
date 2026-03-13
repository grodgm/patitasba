#!/bin/bash
cd "/Users/gonzalorodriguez/Desktop/Patitas"
echo "--- $(date) ---" >> "/Users/gonzalorodriguez/Desktop/Patitas/scraper.log"
/Library/Frameworks/Python.framework/Versions/3.14/bin/python3 scraper.py >> "/Users/gonzalorodriguez/Desktop/Patitas/scraper.log" 2>&1
echo "Completado." >> "/Users/gonzalorodriguez/Desktop/Patitas/scraper.log"
