#!/usr/bin/env python
import argparse
import logging
import multiprocessing
import time
from functools import partial, update_wrapper
from defaults import EXTRACTION_MAX_READ_PAIRS

import pysam


compl_table = [chr(i) for i in xrange(256)]
compl_table[ord('A')] = 'T'
compl_table[ord('C')] = 'G'
compl_table[ord('G')] = 'C'
compl_table[ord('T')] = 'A'


def compl(seq):
    return "".join([compl_table[ord(i)] for i in seq])


def get_sequence_quality(aln):
    if not aln.is_reverse:
        return aln.seq.upper(), aln.qual

    return compl(aln.seq.upper())[::-1], aln.qual[::-1]


def write_read(fd, aln):
    end_id = 1 if aln.is_read1 else 2

    sequence, quality = get_sequence_quality(aln)
    fd.write("@%s/%d\n%s\n+\n%s\n" % (aln.qname, end_id, sequence, quality))


# Returns true if the alignment is soft of hard clipped
# on both sides or if it is unmapped
def is_clipped_both(aln):
    if aln.cigar is None:
        return True
    clipped_left = aln.cigar[0][0] == 4 or aln.cigar[0][0] == 5
    clipped_right = aln.cigar[-1][0] == 4 or aln.cigar[-1][0] == 5
    return clipped_left and clipped_right


# this is the criteria to keep a read
def keep_read(aln, aln_chr, chromosome, start, end):
    return aln_chr == chromosome and (
        not is_clipped_both(aln)) and aln.mapq >= 40 and start <= aln.pos < end


# this function will determine whether the pair is kept
# at all (all or some)
def keep_pair(aln, mate, aln_chr, mate_chr, chromosome, start, end):
    if keep_read(aln, aln_chr, chromosome, start, end):
        return True
    if keep_read(mate, mate_chr, chromosome, start, end):
        return True
    return False


def is_all(aln, mate):
    return (
        (aln.cigarstring == '100M' and mate.cigarstring == '100M') and ( aln.is_proper_pair and mate.is_proper_pair))


def all_pair(aln, mate):
    return True


def non_perfect(aln, mate):
    return not (aln.cigarstring == "100M" and mate.cigarstring == "100M" and aln.is_proper_pair and mate.is_proper_pair)


def discordant(aln, mate, isize_min=300, isize_max=400):
    if aln.tlen == 0: return True
    return not (isize_min <= abs(aln.tlen) <= isize_max)


def discordant_with_normal_orientation(aln, mate, isize_min=300, isize_max=400):
    if aln.tlen == 0: return True
    if aln.is_reverse and mate.is_reverse or not aln.is_reverse and not mate.is_reverse: return False
    return not (isize_min <= abs(aln.tlen) <= isize_max)


def extract_read_pairs(bamname, region, prefix, extract_fns, pad=0, max_read_pairs=EXTRACTION_MAX_READ_PAIRS):
    logger = logging.getLogger("%s-%s" % (extract_read_pairs.__name__, multiprocessing.current_process()))

    extract_fn_names = [extract_fn.__name__ for extract_fn in extract_fns]
    logger.info("Extracting reads from %s for region %s with padding %d using functions %s" % (
        bamname, region, pad, extract_fn_names))

    chr_name = region.split(':')[0]
    chr_start = int(region.split(':')[1].split("-")[0]) - pad
    chr_end = int(region.split(':')[1].split('-')[1]) + pad

    selected_pair_counts = [0] * len(extract_fn_names)
    aln_list = []

    start_time = time.time()

    bam = pysam.Samfile(bamname, "rb")
    if chr_start < 0:
        logger.error("Skipping read extraction since interval too close to chromosome beginning")
    else:
        # Read alignments from the interval in memory and build a dictionary to get mate instead of calling bammate.mate() function
        aln_list = [aln for aln in bam.fetch(chr_name, start=chr_start, end=chr_end) if not aln.is_secondary]

    aln_dict = {}
    for aln in aln_list:
        if aln.qname not in aln_dict:
            aln_dict[aln.qname] = [None, None]
        aln_dict[aln.qname][0 if aln.is_read1 else 1] = aln

    aln_pairs = []
    if len(aln_dict) <= max_read_pairs:
        logger.info("Building mate dictionary from %d reads" % len(aln_list))
        for aln_pair in aln_dict.values():
            missing_index = 0 if aln_pair[0] is None else (1 if aln_pair[1] is None else 2)
            if missing_index < 2:
                mate = None
                try:
                    mate = bam.mate(aln_pair[1-missing_index])
                except ValueError:
                    pass
                if mate is not None:
                    aln_pair[missing_index] = mate
                    aln_pairs.append(aln_pair)
            else:
                aln_pairs.append(aln_pair)
    else:
        logger.info("Too many reads encountered. Skipping read extraction.")

    bam.close()

    ends = [(open("%s_%s_1.fq" % (prefix, name), "w"), open("%s_%s_2.fq" % (prefix, name), "w")) for name in
            extract_fn_names]
    for first, second in aln_pairs:
        for fn_index, extract_fn in enumerate(extract_fns):
            if extract_fn(first, second):
                write_read(ends[fn_index][0], first)
                write_read(ends[fn_index][1], second)

                selected_pair_counts[fn_index] += 1

    for end1, end2 in ends:
        end1.close()
        end2.close()

    logger.info("Examined %d pairs in %g seconds" % (len(aln_pairs), time.time() - start_time))
    logger.info("Extraction counts %s" % (zip(extract_fn_names, selected_pair_counts)))

    return zip([(end[0].name, end[1].name) for end in ends], selected_pair_counts)


if __name__ == "__main__":
    FORMAT = '%(levelname)s %(asctime)-15s %(name)-20s %(message)s'
    logging.basicConfig(level=logging.INFO, format=FORMAT)

    parser = argparse.ArgumentParser(description="Extract reads and mates from a region for spades assembly",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--bam", help="BAM file to extract reads from", required=True)
    parser.add_argument("--region", help="Samtools region string", required=True)
    parser.add_argument("--prefix", help="Output FASTQ prefix", required=True)
    parser.add_argument("--extract_fn", help="Extraction function", choices=["all_pair", "non_perfect", "discordant"],
                        default="all_pair")
    parser.add_argument("--pad", help="Padding to apply on both sides of the interval", type=int, default=0)
    parser.add_argument("--isize_min", help="Minimum insert size", default=200, type=int)
    parser.add_argument("--isize_max", help="Maximum insert size", default=500, type=int)
    parser.add_argument("--max_read_pairs", help="Maximum read pairs to extract for an interval", default=EXTRACTION_MAX_READ_PAIRS, type=int)

    args = parser.parse_args()

    if args.extract_fn == 'all_pair':
        extract_fn = all_pair
    elif args.extract_fn == 'non_perfect':
        extract_fn = non_perfect
    else:
        extract_fn = partial(discordant, isize_min=args.isize_min, isize_max=args.isize_max)
        update_wrapper(extract_fn, discordant)

    extract_read_pairs(args.bam, args.region, args.prefix, [extract_fn], pad=args.pad, max_read_pairs=args.max_read_pairs)
