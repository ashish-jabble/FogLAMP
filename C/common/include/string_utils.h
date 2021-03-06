#ifndef _STRING_UTILS_H
#define _STRING_UTILS_H
/*
 * FogLAMP utilities functions for handling stringa
 *
 * Copyright (c) 2019 Dianomic Systems
 *
 * Released under the Apache 2.0 Licence
 *
 * Author: Stefano Simonelli
 */

#include <string>

using namespace std;

void StringReplace(std::string& StringToManage,
		   const std::string& StringToSearch,
		   const std::string& StringReplacement);


#endif
