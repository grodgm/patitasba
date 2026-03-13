#!/bin/bash
cd "/Users/gonzalorodriguez/Desktop/Patitas"
echo "--- $(date) ---" >> "/Users/gonzalorodriguez/Desktop/Patitas/scraper.log"
bash deploy_a_github.sh >> "/Users/gonzalorodriguez/Desktop/Patitas/scraper.log" 2>&1
echo "Completado." >> "/Users/gonzalorodriguez/Desktop/Patitas/scraper.log"
