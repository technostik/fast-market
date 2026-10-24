# YouTube transfer (joriel -> techno_sophia)

1. Generate candidates:
   python transfer/generate_csv.py
   -> transfer/candidates.csv

2. Open candidates.csv in a spreadsheet, fill `selected` column with x/yes for videos to transfer.

3. Convert selection:
   python transfer/select_videos.py
   -> transfer/selected_videos.json

4. Transfer (unlisted by default):
   python transfer/transfer_videos.py --privacy unlisted
   # resume after interruption:
   python transfer/transfer_videos.py --resume
   # dry run:
   python transfer/transfer_videos.py --dry-run
