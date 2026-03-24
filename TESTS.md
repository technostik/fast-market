# micro by hand test suite

prompt apply "say something" -P openai-compatible
corpus sync
task task "Do the 3 following thing : 1/ with corpus get the transcription of 'eiatJdCg7MM' and 2/ make a marketing analysis in French of it's content, and 3/ send me the result on telegram" -P openai-compatible -o last-prompt-session.yaml
message alert "yo"
monitor run --limit 1 --force
image generate "a yewllow glowing cat"
youtube get-last --short | xargs -d '\n' -n2 sh -c 'tiktok upload-yt-short -t "$0" -u "$1"'
