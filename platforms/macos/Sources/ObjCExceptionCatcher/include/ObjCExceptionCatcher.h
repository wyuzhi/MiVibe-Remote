#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Executes `block` and returns an exception description if Objective-C code raises.
///
/// AVFAudio still raises NSException for some hardware reconfiguration races. Swift
/// error handling cannot catch those exceptions, so the bridge must stay at this
/// narrow Objective-C boundary.
FOUNDATION_EXPORT NSString * _Nullable MiVibeCatchObjectiveCException(
    NS_NOESCAPE void (^block)(void)
);

NS_ASSUME_NONNULL_END
