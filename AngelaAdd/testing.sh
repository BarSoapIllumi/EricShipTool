#!/bin/bash

string='Paris, France, Europe';
readarray -td, arr <<<"$string"; unset 'a[-1]'; declare -p arr;

