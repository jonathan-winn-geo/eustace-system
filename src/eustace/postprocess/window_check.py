"""Persistence checks in QC flags for EUSTACE analysis products"""

import argparse
import os.path
import numpy
from dateutil.relativedelta import relativedelta
import datetime
from dateutil import parser

import iris

from eustace.outputformats.outputvariable import OutputVariable
from eustace.outputformats.globalfield_filebuilder import FileBuilderGlobalField
from eumopps.version.svn import get_revision_id_for_module
from netCDF4 import default_fillvals
from eustace.outputformats import definitions
import eustace.timeutils.epoch

from apply_mask import load_flags, save_flag_file

from operation_count import operation_dates
import flags

# bit mask flags used in output file
FLAG_TYPE = flags.FLAG_TYPE
TYPE_NAME = flags.TYPE_NAME
FLAG_MAX_N = flags.FLAG_MAX_N
FLAG_MAX_USED = flags.FLAG_MAX_USED
NULL_FLAG = flags.NULL_FLAG

# time window checks
DAY_FLAG = flags.DAY_FLAG
PRIOR_WINDOW_FLAG = flags.PRIOR_WINDOW_FLAG
POST_WINDOW_FLAG = flags.POST_WINDOW_FLAG

# calendar day checks
CALENDAR_DAY_FLAG    = flags.CALENDAR_DAY_FLAG
PRIOR_CALENDAR_FLAG  = flags.PRIOR_CALENDAR_FLAG
POST_CALENDAR_FLAG   = flags.POST_CALENDAR_FLAG

# slow component uncertatinty thresholds
CLIMATOLOGY_UNC_FLAG  = flags.CLIMATOLOGY_UNC_FLAG
LARGE_SCALE_UNC_FLAG  = flags.LARGE_SCALE_UNC_FLAG

# extreme value checks
AREAL_LOW_FLAG      = flags.AREAL_LOW_FLAG
AREAL_HIGH_FLAG     = flags.AREAL_HIGH_FLAG
EXTREME_LOW_FLAG    = flags.EXTREME_LOW_FLAG
EXTREME_HIGH_FLAG   = flags.EXTREME_HIGH_FLAG

# omitted data source flags
MISSING_MARINE_FLAG  = flags.MISSING_MARINE_FLAG

# missing data indicator
MISSING_FLAG_FLAG    = flags.MISSING_FLAG_FLAG

FLAG_MEANINGS = flags.FLAG_MEANINGS


"""

Core method for thresholding on observation influence

"""

def local_window_constraint_checks(input_directory, output_directory, iteration, reference_time, window_range, count_threshold, target_flag):
    """check constraint in a local window of +/- n days"""
    
    # initialise contraint flags to None
    constraint_count = None
    prior_constraint_count = None
    post_constraint_count = None
    day_constraint_flag = None
    
    # loop over window to check the constraint
    for dayshift in range(-window_range, window_range+1):
    
        # get the day's analysis data
        day_to_load = reference_time + relativedelta(days=dayshift)
        print day_to_load
        datestring = "{:04d}{:02d}{:02d}".format(day_to_load.year, day_to_load.month, day_to_load.day )
        try:
            reference_flags = load_flags(input_directory, iteration, datestring)
            reference_flags = numpy.squeeze(reference_flags.data[:,:,:])
        except:
            print "failed to load", datestring
            print input_directory
            continue
    
    
        if dayshift == 0:
            # get and keep the flag values for the centre day
            flag_values = reference_flags
        else:
            # check to see if constrained and accumulate prior/post count
            
            # apply constraint threshold check for this day
            isconstrained = ~(numpy.bitwise_and(reference_flags, target_flag) == target_flag)
            print isconstrained
            if prior_constraint_count is None:
                prior_constraint_count = numpy.zeros(isconstrained.shape, numpy.int64)
            if post_constraint_count is None:
                post_constraint_count = numpy.zeros(isconstrained.shape, numpy.int64)
                
            # number of previous days constrained in window
            if dayshift < 0:
                prior_constraint_count[isconstrained]+=1

            # number of following days constrained in window                
            if dayshift > 0:
                post_constraint_count[isconstrained]+=1

    # compute summary flags          
    prior_constrained = prior_constraint_count < count_threshold
    post_constrained = post_constraint_count < count_threshold


    # set flag values for output
    flag_values[prior_constrained] = flag_values[prior_constrained] | PRIOR_WINDOW_FLAG
    flag_values[post_constrained] = flag_values[post_constrained] | POST_WINDOW_FLAG

    return flag_values




"""

Calls setup to run as batches in lsf

"""

def flagging_operation( reference_time_string,
                        operation_index,
                        input_directory,
                        iteration,
                        output_directory,
                        window_range,
                        count_threshold,
                        target_flag ):

    # get dates in the month to be processed in this operation
    reference_time = parser.parse(reference_time_string)
    processing_dates = operation_dates(reference_time, operation_index)
    
    # derive flags for each day
    for processdate in processing_dates:
        
        # check that directory exists and if not then make it
        if not os.path.exists(os.path.join(output_directory, str(processdate.year))):
            os.makedirs(os.path.join(output_directory, str(processdate.year)))

        flag_values = local_window_constraint_checks(  input_directory,
                                                       output_directory,
                                                       iteration,
                                                       processdate,
                                                       window_range,
                                                       count_threshold,
                                                       target_flag )

        # set flag values for output
        #flag_values = numpy.zeros( definitions.GLOBAL_FIELD_SHAPE[1:], FLAG_TYPE )


        # save to NetCDF
        outputfile = os.path.join(output_directory, '{:04d}'.format(processdate.year), 'eustace_analysis_{:d}_qc_flags_{:04d}{:02d}{:02d}.nc'.format(iteration, processdate.year, processdate.month, processdate.day))
        save_flag_file(flag_values, processdate, outputfile)

def main():

    print 'Submission of advanced standard analysis observation constraint flagging jobs'
    
    argparser = argparse.ArgumentParser(description='Monthly batches of masking operations')
    
    argparser.add_argument('--reference_time_string', type=str, default="1880-01-01", help='reference first day to run formatted YYY-MM-DD. Should be first day of month.')
    argparser.add_argument('--operation_index',  type=int, default=0, help='the number of months since the reference_time_string that this masking operation corresponds to')
    argparser.add_argument('--input_directory', type=str, default="/gws/nopw/j04/eustace_vol2/masking/", help='location of QC flag file to be used as an input')
    argparser.add_argument('--iteration',  type=int, default=9, help='operation index at which the analysis grid produced')
    argparser.add_argument('--output_directory',  type=str, default="/gws/nopw/j04/eustace_vol2/masking/", help='operation index at which the analysis grid produced')
    argparser.add_argument('--window_range',  type=int, default=15, help='+/- range of the search window in days')
    argparser.add_argument('--count_threshold',  type=int, default=5, help='number of constrained days in the window range (prior or following this day) required for window flags')

    args = argparser.parse_args()

    flagging_operation( args.reference_time_string,
                        args.operation_index,
                        args.input_directory,
                        args.iteration,
                        args.output_directory,
                        args.window_range,
                        args.count_threshold,
                        DAY_FLAG )

if __name__ == '__main__':
    
    main()
    
