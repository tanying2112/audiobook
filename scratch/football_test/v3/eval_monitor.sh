#!/bin/bash
until grep -q "EV3_DONE" /private/tmp/claude-501/-Users-guwj-Documents-audiobook/ff3db756-5748-41da-b472-441125d62f1d/tasks/bti0angqi.output 2>/dev/null; do
    sleep 10
done
cat /private/tmp/claude-501/-Users-guwj-Documents-audiobook/ff3db756-5748-41da-b472-441125d62f1d/tasks/bti0angqi.output
