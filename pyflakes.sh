#!/bin/bash
find -maxdepth 1 -type d | grep -vP "^.($|/dissemin|/notification|/src|/\..*)" | xargs pyflakes > pyflakes.out
cat pyflakes.out
test \! -s pyflakes.out
